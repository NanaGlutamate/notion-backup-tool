from typing import Callable
from vfs import Node
from notionapi import *
import json
import requests
import time


invalid_chars = ['/', '\\', '?', '%', '*', ':', '|', '"', '<', '>', '.']
def kv_to_name(key: str, value: dict) -> str:
    if 'type' in value:
        type = value['type']
        if 'title' in value[type]:
            title = value[type]['title']
            for c in invalid_chars:
                title = title.replace(c, '_')
            return f"[{type.replace('child_', '')}]{title[:40]}"
        return f"[{type.replace('child_', '')}]{key}"
    return key

class DictCache:
    def __init__(
            self,
            root_dir: str,
            indent: int | None = 4,
            kv_to_name: Callable[[str, dict], str] = kv_to_name,
        ):
        __start_time = time.time()
        self.inner_cache = dict()
        self.root = Node(None, root_dir)
        self.key_to_path: dict[str, Node] = dict()
        self.kv_to_name = kv_to_name
        self.indent = indent

        # 加载磁盘缓存
        def dfs(node: Node):
            for file in node.listdir():
                if not isinstance(file, str):
                    dfs(file)
                    continue
                if not file.endswith('.json') or file.startswith('.'):
                    continue
                with open(node.real_path + '/' + file, 'r', encoding='utf-8') as f:
                    key = self.__path_to_key(node)
                    self.inner_cache[key] = json.load(f)
                    self.set_vpath(key, node)
        dfs(self.root)
        profiler['DictCache::__init__()'].append(time.time() - __start_time)

    def get_cache(self, key: str):
        if key not in self.inner_cache:
            return None
        return self.inner_cache[key]

    def set_cache(self, key: str, value: any):
        self.inner_cache[key] = value
        path = self.key_to_path[key]
        with open(f'{path.real_path}/{self.kv_to_name(key, value)}.json', 'w', encoding='utf-8') as f:
            json.dump(self.inner_cache[key], f, indent=self.indent, ensure_ascii=False)

    def get_vpath(self, key: str) -> Node | None:
        return self.key_to_path[key] if key in self.key_to_path else None

    def set_vpath(self, key: str, path: Node):
        self.key_to_path[key] = path

    def __path_to_key(self, node: Node) -> str:
        return node.parent.real_to_vname[node.real_name]

class TreeCache:
    def __init__(self, dir: str):
        __start_time = time.time()
        self.dict_cache = DictCache(dir)
        self.__id_to_node = dict()
        self.__modified_pg_to_id = dict()
        self.__cache_file_list: list[tuple[str, bytes]] = []

        def dfs(node: dict, pg_id: str):
            if '_children' in node:
                for i in node['_children']:
                    dfs(i, pg_id)
            if 'id' in node:
                self.__id_to_node[node['id'], pg_id] = node
        for pg_id, pg_node in self.dict_cache.inner_cache.items():
            dfs(pg_node, pg_id)
        profiler['TreeCache::__init__()'].append(time.time() - __start_time)

    def get_page_path(self, pg_id: str) -> Node | None:
        return self.dict_cache.get_vpath(pg_id)

    def get_node(self, id: str) -> dict:
        __start_time = time.time()
        id = self.__to_uuid(id)
        if not self.dict_cache.get_vpath(id):
            self.dict_cache.set_vpath(id, self.dict_cache.root.mkdir(id))
        if self.__flush_node_if_need(id, id):
            self.__write_cache()
        profiler['TreeCache::get_node()'].append(time.time() - __start_time)
        return self.__id_to_node[id, id]
    
    def gc(self, root_pg_ids: list[dict]):
        __start_time = time.time()
        marked = set()
        def marker(n: dict, pg_id: str):
            nonlocal marked
            if n['type'] in ['child_page', 'child_database']:
                marked.add(n['id'])
                id = n['id']
                if id != pg_id:
                    marker(self.__id_to_node[id, id], id)
            if '_children' in n:
                for i in n['_children']:
                    marker(i, pg_id)
            if 'data' in n and n['type'] == 'child_database':
                for i in n['data']:
                    id = i['id']
                    marker(self.__id_to_node[id, id], id)
        for r in root_pg_ids:
            uuid = self.__to_uuid(r)
            marker(self.__id_to_node[uuid, uuid], uuid)
        profiler['TreeCache::gc()::mark'].append(time.time() - __start_time)
        
        __start_time = time.time()
        for pg_id in [i for i in self.dict_cache.inner_cache]:
            if not pg_id in marked:
                print(f'delete node[{pg_id}]')
                vpath = self.dict_cache.get_vpath(pg_id)
                parent = vpath.parent
                parent.removedirs(parent.real_to_vname[vpath.real_name])
        profiler['TreeCache::gc()::sweep'].append(time.time() - __start_time)
        

    def get_database(self, id: str) -> list[dict]:
        __start_time = time.time()
        node = self.get_node(id)
        profiler['TreeCache::get_database()'].append(time.time() - __start_time)
        return node['data']
    
    def __to_uuid(self, id: str) -> str:
        if len(id) == 32:
            return id[:8] + '-' + id[8:12] + '-' + id[12:16] + '-' + id[16:20] + '-' + id[20:]
        return id

    def __flush_node_if_need(self, id: str, pg_id: str, new_value: dict | None = None):
        """
            will not write file cache; return if modified
        """
        if new_value is None:
            new_value = notion_get_block(id)
        assert new_value['id'] == id

        # update cache
        if not self.__update_cache(id, pg_id, new_value):
            return False
        
        new_value = self.__id_to_node[id, pg_id]
        # clip leaf sub-page
        if new_value['type'] == 'child_page' and id != pg_id:
            if '_children' in new_value:
                del new_value['_children']
            return True
        
        # fetch child database
        self.__fetch_database_data(new_value, pg_id)
        # fetch img and file
        self.__fetch_file_and_img(new_value, pg_id)

        # fetch child nodes
        self.__fetch_child_nodes(new_value, pg_id)
        return True
    
    def __update_cache(self, id: str, pg_id: str, new_value: dict) -> bool:
        """ return if cache modified """
        if (id, pg_id) not in self.__id_to_node:
            # cache miss, insert new node
            if id != pg_id:
                assert self.__id_to_node[pg_id, pg_id]['type'] in ['child_page', 'child_database']
            else:
                assert new_value['type'] in ['child_page', 'child_database']
            self.__id_to_node[id, pg_id] = new_value
            # mark dirty
            self.__mark_dirty(id, pg_id)
            return True
        # regard database always cache miss
        if new_value['type'] != 'child_database' and self.__id_to_node[id, pg_id]['last_edited_time'] == new_value['last_edited_time']:
            # cache hit
            return False
        # cache miss
        self.__id_to_node[id, pg_id].clear()
        for k, v in new_value.items():
            self.__id_to_node[id, pg_id][k] = v
        # mark dirty
        self.__mark_dirty(id, pg_id)
        return True
    
    def __mark_dirty(self, id: str, pg_id: str):
        if pg_id not in self.__modified_pg_to_id:
            self.__modified_pg_to_id[pg_id] = []
        self.__modified_pg_to_id[pg_id].append(id)
    
    def __fetch_database_data(self, new_value: dict, pg_id: str):
        if new_value['type'] != 'child_database':
            return
        db_id = new_value['id']
        if db_id != pg_id:
            return
        ans = notion_get_database_data(db_id)
        self.__id_to_node[db_id, pg_id] = { **new_value, 'data': ans }
        for row in ans:
            self.dict_cache.set_vpath(row['id'], self.dict_cache.get_vpath(pg_id).mkdir(row["id"]))
            self.__flush_node_if_need(row['id'], row['id'])
    
    def __fetch_file_and_img(self, new_value: dict, pg_id: str):
        if new_value['type'] != 'image' and new_value['type'] != 'file':
            return
        type = new_value['type']
        inner_type = new_value[type]['type']
        if 'url' not in new_value[type][inner_type]:
            print('[WARNING] unknown json structure: ' + str(new_value))
            return
        url = new_value[type][inner_type]['url']
        if 'expiry_time' in new_value[type][inner_type]:
            del new_value[type][inner_type]['expiry_time']

        if type == 'image':
            origin_file_name = url.split('/')[-1].split('?')[0]
            file_name = f'{new_value["id"]}.{origin_file_name.split(".")[-1]}'
        elif type == 'file':
            file_name = f'{new_value["id"]}_{new_value["file"]["name"]}'
        else:
            file_name = f'{new_value["id"]}'
        new_value[type][inner_type]['url'] = file_name
        # download url to file_name
        self.__cache_file_list.append((f'{self.dict_cache.get_vpath(pg_id).real_path}/{file_name}', requests.get(url).content))

    def __fetch_child_nodes(self, new_value: dict, pg_id: str):
        # update children if cache miss or insert new node
        if not '_children' in new_value:
            return
        id = new_value['id']
        for i in notion_get_block_children(id):
            child_id = i['id']
            if i['type'] in ['child_page', 'child_database']:
                self.dict_cache.set_vpath(child_id, self.dict_cache.get_vpath(pg_id).mkdir(child_id))
                self.__flush_node_if_need(child_id, child_id, { k: v for k, v in i.items() })
            self.__flush_node_if_need(child_id, pg_id, i)
            new_value['_children'].append(self.__id_to_node[child_id, pg_id])

    def __write_cache(self):
        __start_time = time.time()
        for k, v in self.__modified_pg_to_id.items():
            if not (k in v and len(v) == 1):
                print(f"cache miss in page[{k}]: {v}")
            self.dict_cache.set_cache(k, self.__id_to_node[k, k])
        self.__modified_pg_to_id.clear()
        for path, content in self.__cache_file_list:
            print(f"write file: {path}")
            with open(path, 'wb') as f:
                f.write(content)
        self.__cache_file_list.clear()
        profiler['TreeCache::__write_cache()'].append(time.time() - __start_time)
    
tree_cache = TreeCache('.notion_cache')

def get_all_sub_page_nodes(root: str) -> list[dict]:
    __start_time = time.time()
    root: dict = tree_cache.get_node(root)
    ans = [root]
    def dfs(node: dict):
        nonlocal ans
        if '_children' in node:
            for i in node['_children']:
                if i['type'] == 'child_page':
                    id = i['id']
                    ans += get_all_sub_page_nodes(id)
                dfs(i)
    dfs(root)
    profiler['get_all_sub_page_nodes()'].append(time.time() - __start_time)
    return ans

def get_database(root: str) -> list[dict]:
    return tree_cache.get_database(root)

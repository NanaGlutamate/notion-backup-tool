from profiler import profiler
import os
import json
import time
import shutil

# 避免路径过长带来的问题，将虚拟路径映射到真实路径；虚拟路径可能为xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx/...
# 但是真实路径只是1a/1/2/c...
# 每个文件夹下都会有一个.keymap.json, 将该文件夹下的虚拟路径映射到真实路径
class Node:
    def __init__(self, parent: 'Node | None', real_name: str):
        __start_time = time.time()
        self.parent = parent
        self.real_name = real_name
        self.real_path = (parent.real_path + '/' + real_name) if parent else real_name
        os.makedirs(self.real_path, exist_ok=True)
        if os.path.exists(f'{self.real_path}/.keymap.json'):
            with open(f'{self.real_path}/.keymap.json', 'r', encoding='utf-8') as f:
                self.vname_to_real = json.load(f)
        else:
            self.vname_to_real = dict()
        self.real_to_vname = { r: v for v, r in self.vname_to_real.items() }
        if not len(self.vname_to_real) == len(self.real_to_vname):
            print(self.vname_to_real, self.real_to_vname)
            raise Exception("not match")
        # vname -> Node
        self.vname_to_child_node: dict[str, 'Node'] = dict()
        for dir in os.listdir(self.real_path):
            if os.path.isdir(f'{self.real_path}/{dir}'):
                if dir not in self.real_to_vname:
                    shutil.rmtree(path=f'{self.real_path}/{dir}')
                self.vname_to_child_node[self.real_to_vname[dir]] = Node(self, dir)
        profiler['Node::__init__()'].append(time.time() - __start_time)
        
    def removedirs(self, vname: str):
        assert vname.find('/') == -1 and vname.find('\\') == -1
        shutil.rmtree(path=self.vname_to_child_node[vname].real_path)
        del self.vname_to_child_node[vname]

    def mkdir(self, vname: str) -> 'Node':
        assert vname.find('/') == -1 and vname.find('\\') == -1
        if vname not in self.vname_to_child_node:
            new_real = '{:x}'.format(len(self.vname_to_real))
            new_node = Node(self, new_real)
            self.vname_to_child_node[vname] = new_node
            self.vname_to_real[vname] = new_real
            self.real_to_vname[new_real] = vname
            self.__write_keymap()
        return self.vname_to_child_node[vname]

    def listdir(self) -> list['str | Node']:
        return [i for i in self.vname_to_child_node.values()] + \
               [i for i in os.listdir(self.real_path) if not os.path.isdir(f'{self.real_path}/{i}')]

    def __write_keymap(self):
        __start_time = time.time()
        with open(f'{self.real_path}/.keymap.json', 'w', encoding='utf-8') as f:
            json.dump(self.vname_to_real, f, indent=4, ensure_ascii=False)
        profiler['Node::__write_keymap()'].append(time.time() - __start_time)

from notion_client import Client
from typing import Callable
from functools import cache
from profiler import profiler
import json
import time

# 从.env.local文件或命令行参数读取NOTION_TOKEN
config = None
with open('config.json', 'r') as f:
    config = json.load(f)

notion = Client(auth=config['NOTION_TOKEN'])

def clip_block(block: dict):
    if 'created_time' in block: del block['created_time']
    if 'created_by' in block: del block['created_by']
    if 'last_edited_by' in block: del block['last_edited_by']
    if 'archived' in block: del block['archived']
    if 'in_trash' in block: del block['in_trash']
    if 'parent' in block: del block['parent']
    if 'object' in block: del block['object']
    if 'request_id' in block: del block['request_id']
    if 'has_children' in block:
        if block['has_children']:
            block['_children'] = []
        del block['has_children']

# cached notion APIs
@cache
def notion_get_block(block_id: str) -> dict:
    __start_time = time.time()
    block = notion.blocks.retrieve(block_id=block_id)
    clip_block(block)
    profiler['notion_get_block()'].append(time.time() - __start_time)
    return block

@cache
def notion_get_paged_list(api: Callable[[str], list[dict]], id: str) -> list[dict]:
    res = api(id)
    ans = res["results"]
    while res["has_more"]:
        res = api(id, start_cursor=res["next_cursor"])
        ans.extend(res["results"])
    for i in ans:
        clip_block(i)
    return ans

def notion_get_block_children(id: str) -> list[dict]:
    __start_time = time.time()
    ans = notion_get_paged_list(notion.blocks.children.list, id)
    profiler['notion_get_block_children()'].append(time.time() - __start_time)
    return ans

def notion_get_database_data(id: str) -> list[dict]:
    __start_time = time.time()
    ans = notion_get_paged_list(notion.databases.query, id)
    profiler['notion_get_database_data()'].append(time.time() - __start_time)
    return ans
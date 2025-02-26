from notionlib import *

debug_mode = True

# 获取所有页面
for node in config['PG_ID']:
    tree_cache.get_node(node)
    
for k, v in [i for i in tree_cache.dict_cache.inner_cache.items()]:
    # 数据库修改不会影响最后修改时间，只能全部强制刷新；新增数据库没有必要强制刷新，只刷新已有的就行
    if v['type'] == 'child_database':
        try:
            tree_cache.get_node(v['id'])
        except Exception as e:
            print(e)
            
tree_cache.gc(config['PG_ID'])

for name, times, total, mean in sorted([(k, len(v), sum(v), sum(v) / len(v)) for k, v in profiler.items()], key=lambda x: -x[2]):
    print('{:<30}: {:>5} times, total {:>15.5} s, mean {:>15.5} ms'.format(name, times, total, mean * 1_000))


import os
import shutil

src_root = './characters'
dst_root = './assets'

for root, dirs, files in os.walk(src_root):
    if 'prompt.txt' in files:
        rel_path = os.path.relpath(root, src_root)
        dst_dir = os.path.join(dst_root, rel_path)
        os.makedirs(dst_dir, exist_ok=True)
        src_file = os.path.join(root, 'prompt.txt')
        dst_file = os.path.join(dst_dir, 'prompt.txt')
        shutil.move(src_file, dst_file)
import os

root_dir = './assets'

for dirpath, dirnames, filenames in os.walk(root_dir):
    for filename in filenames:
        full_path = os.path.join(dirpath, filename)
        if filename.lower().endswith('.mp3'):
            new_path = os.path.join(dirpath, 'audio.mp3')
            if full_path != new_path:
                os.rename(full_path, new_path)
        elif filename.lower().endswith('.txt'):
            new_path = os.path.join(dirpath, 'ref_text.txt')
            if full_path != new_path:
                os.rename(full_path, new_path)
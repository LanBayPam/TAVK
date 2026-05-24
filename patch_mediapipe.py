import pathlib

f = pathlib.Path(r'C:\Users\ASUS\AppData\Local\Programs\Python\Python311\Lib\site-packages\mediapipe\tasks\python\core\optional_dependencies.py')
txt = f.read_text()

if 'try:' not in txt:
    txt = txt.replace(
        'from tensorflow.tools.docs import doc_controls',
        'try:\n    from tensorflow.tools.docs import doc_controls\nexcept Exception:\n    doc_controls = None'
    )
    f.write_text(txt)
    print('Patched successfully!')
else:
    print('Already patched, no changes needed.')

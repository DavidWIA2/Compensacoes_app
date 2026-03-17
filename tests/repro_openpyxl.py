
import openpyxl
from zipfile import BadZipFile
import os

with open('test_corrupt.xlsx', 'w') as f:
    f.write('stub')

try:
    openpyxl.load_workbook('test_corrupt.xlsx')
    print('Success')
except BadZipFile:
    print('BadZipFile')
except Exception as e:
    print(f'Error: {type(e).__name__}: {e}')
finally:
    if os.path.exists('test_corrupt.xlsx'):
        os.remove('test_corrupt.xlsx')

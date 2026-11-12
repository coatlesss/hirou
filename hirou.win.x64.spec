# -*- mode: python ; coding: utf-8 -*-
# pyinstaller --noconfirm hirou.win.x64.spec   ->   dist\HIROU\HIROU.exe
# A folder build, not one file: the CUDA libraries are ~2 GB and a one-file exe would unpack them on every start.
import glob
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

site_packages = os.path.join(sys.prefix, 'Lib', 'site-packages')
# the nvidia wheels are namespace packages, so collect their DLLs by path (hirou/listen.py finds them in nvidia/*/bin)
cuda_dlls = [(dll, os.path.relpath(os.path.dirname(dll), site_packages))
             for dll in glob.glob(os.path.join(site_packages, 'nvidia', '*', 'bin', '*.dll'))]
# janome's default (mmap) mode reads its dictionary straight from these .py files on disk, so ship them as files too
janome_dict = [(f, 'janome/sysdic') for pattern in ('entries_compact[0-9].py', 'entries_extra[0-9].py')
               for f in glob.glob(os.path.join(site_packages, 'janome', 'sysdic', pattern))]

a = Analysis(
    ['src\\hirou\\main.py'],
    pathex=['src'],
    binaries=cuda_dlls + collect_dynamic_libs('ctranslate2'),
    datas=[('src/hirou/resources', 'hirou/resources')] + collect_data_files('faster_whisper') + janome_dict,
    hiddenimports=collect_submodules('janome') + ['pynput.keyboard._win32', 'pynput.mouse._win32'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='HIROU',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon='src\\hirou\\resources\\icon.ico',
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='HIROU')

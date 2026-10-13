"""Legacy entry point for local configuration presence checks.

The active app is backend/main.py and the setup workflow is scripts/setup.ps1.
No credential values are printed by this helper.
"""
from pathlib import Path
from shutil import copyfile

from config import configuration_status


def main():
    root = Path(__file__).resolve().parent
    target = root / '.env'
    if not target.exists():
        copyfile(root / '.env.example', target)
        print('Created backend/.env from the template; fill it locally.')
    for name, state in configuration_status().items():
        print(f'{name}: {"configured" if state["configured"] else "missing"}')
    print('Use scripts/setup.ps1 and scripts/migrate_stage1.py for the active app.')


if __name__ == '__main__':
    main()

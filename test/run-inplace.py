import os
import sys
import subprocess

def main():
    script_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src')

    if len(sys.argv) >= 2: 
        args = sys.argv[1:]
    else:
        args = []

    subprocess.run(['python3', '-m', 'nikoget'] + args, cwd=script_dir)

if __name__ == '__main__':
    main()

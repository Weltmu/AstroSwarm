import os
import sys

sys.path.insert(0, r"D:\ai\QBotManager\src")
from qbotmanager.core.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
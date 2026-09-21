"""Entry point for python -m run"""
import sys

try:
    from taskipy.cli import main as taskipy_main
except ImportError:
    print("Error: taskipy is not installed. Run: pip install taskipy")
    sys.exit(1)

if __name__ == "__main__":
    sys.exit(taskipy_main())


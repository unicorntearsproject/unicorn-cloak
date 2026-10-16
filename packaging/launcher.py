"""PyInstaller entry script: the frozen app's equivalent of the
`unicorn-cloak` console script."""
from unicorn_cloak.__main__ import run

if __name__ == "__main__":
    run()

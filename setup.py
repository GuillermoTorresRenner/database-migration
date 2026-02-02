from setuptools import setup

setup(
    name="migrate-new-database",
    version="1.0.0",
    py_modules=["migrate"],
    entry_points={
        "console_scripts": [
            "migrate-new-database = migrate:main",
        ],
    },
    install_requires=[
        "pyyaml",
        "inquirer",
        "pymysql",
        "psycopg2-binary",
        "docker",
    ],
)
#!/usr/bin/env python3
from setuptools import setup, find_packages

setup(
    name='WireGuardServerManager',
    version='1.0.0',
    description='WireGuard Server Manager with user management, session monitoring and REST API',
    author='Your Name',
    author_email='your.email@example.com',
    url='https://github.com/yourusername/wireguard-server-manager',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        # 此项目使用Python标准库，无需额外依赖
    ],
    entry_points={
        'console_scripts': [
            'wireguard-manager=main:main',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Topic :: System :: Networking',
        'Topic :: System :: Systems Administration',
    ],
    python_requires='>=3.6',
)
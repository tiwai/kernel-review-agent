#!/usr/bin/env python3
"""Setup script for kernel-review-agent."""

from setuptools import setup, find_packages
import os

# Read version
version = "0.1"

# Read long description
with open('README.md', 'r', encoding='utf-8') as f:
    long_description = f.read()

# Read requirements
with open('requirements.txt', 'r') as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]

setup(
    name='kernel-review-agent',
    version=version,
    author='Takashi Iwai',
    author_email='tiwai@suse.de',
    description='AI-powered agent for automated review of Linux kernel git commits',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/tiwai/kernel-review-agent',
    packages=find_packages(exclude=['test_*', 'debug_dumps']),
    include_package_data=True,
    package_data={
        '': ['prompts/**/*.md'],
    },
    install_requires=requirements,
    python_requires='>=3.8',
    scripts=['kernel_review_agent.py'],
    data_files=[
        # Install prompts to /usr/share/kernel-review-agent/prompts
        ('share/kernel-review-agent/prompts', [
            'prompts/review-core.md',
            'prompts/technical-patterns.md',
            'prompts/false-positive-guide.md',
            'prompts/backport-verification.md',
            'prompts/callstack.md',
            'prompts/inline-template.md',
            'prompts/README.md',
        ]),
        ('share/kernel-review-agent/prompts/subsystem',
         [f'prompts/subsystem/{f}' for f in os.listdir('prompts/subsystem') if f.endswith('.md')]),
        # Install documentation
        ('share/doc/kernel-review-agent', [
            'README.md',
            'QUICKSTART.md',
            'DEBUG_GUIDE.md',
            'LLM_PROVIDERS.md',
            'CONFIGURATION.md',
            'LICENSE',
            'LICENSE-PROMPTS',
            'config.json.example',
        ]),
    ],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Quality Assurance',
        'Topic :: Software Development :: Testing',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Operating System :: POSIX :: Linux',
    ],
    keywords='linux kernel code-review ai llm git',
    project_urls={
        'Bug Reports': 'https://github.com/tiwai/kernel-review-agent/issues',
        'Source': 'https://github.com/tiwai/kernel-review-agent',
    },
)

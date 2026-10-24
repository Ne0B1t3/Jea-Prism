from setuptools import setup, find_packages

setup(
    name="jea-prism",
    version="0.3.0",
    description="WinRM/PSRP client for assessing JEA endpoints in FullLanguage, ConstrainedLanguage and NoLanguage, with password, Kerberos ticket and NTLM pass-the-hash authentication.",
    author="Ne0b1t3",
    url="https://github.com/Ne0b1t3/jea-prism",
    packages=find_packages(),
    install_requires=["pypsrp>=0.8.0","spnego>=0.9.0"],
    entry_points={
        "console_scripts": [
            "jea-prism=jea_prism.cli:main",
        ],
    },
    python_requires=">=3.8",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Topic :: Security",
        "Intended Audience :: Information Technology",
    ],
)

from setuptools import setup

APP = ["flow.py"]
DATA_FILES = ["dictionary.txt"]
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleIdentifier": "com.broganwilliams.wingvox",
        "CFBundleName": "Wingvox",
        "LSUIElement": True,
        "NSMicrophoneUsageDescription": "Wingvox needs microphone access to transcribe your dictation.",
    },
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    # No setup_requires=["py2app"] on purpose. install.sh already installs
    # py2app from requirements.txt, and declaring it here additionally makes
    # setuptools print a deprecation banner (rows of "!!" and asterisks about
    # fetch_build_eggs) in the middle of an otherwise calm install -- which
    # reads as a crash to anyone who isn't a developer.
)

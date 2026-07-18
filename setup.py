from setuptools import setup

APP = ["flow.py"]
DATA_FILES = ["dictionary.txt"]
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleIdentifier": "com.broganwilliams.wingvox",
        "CFBundleName": "WingVox",
        "LSUIElement": True,
        "NSMicrophoneUsageDescription": "WingVox needs microphone access to transcribe your dictation.",
    },
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)

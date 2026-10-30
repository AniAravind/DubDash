from glob import glob
from setuptools import setup

setup(
    name="dubdash", version="0.1.0", packages=["dubdash"],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/dubdash"]),
        ("share/dubdash", ["package.xml"]),
        ("share/dubdash/launch", glob("launch/*.launch.py")),
        ("share/dubdash/config", glob("config/*")),
    ],
    install_requires=["setuptools"], zip_safe=True,
    maintainer="DubDash maintainers", maintainer_email="maintainers@example.com",
    description="DubDash robot integration", license="UNLICENSED",
    entry_points={"console_scripts": [
        "command_guard = dubdash.command_guard:main",
        "person_detector = dubdash.person_detector:main",
        "navigation_supervisor = dubdash.navigation_supervisor:main",
    ]},
)

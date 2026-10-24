from glob import glob
from setuptools import setup

setup(
    name="dubdash_replay", version="0.1.0", packages=["dubdash_replay"],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/dubdash_replay"]),
        ("share/dubdash_replay", ["package.xml"]),
        ("share/dubdash_replay/launch", glob("launch/*.launch.py")),
        ("share/dubdash_replay/config", glob("config/*.rviz")),
    ],
    install_requires=["setuptools"], zip_safe=True,
    maintainer="DubDash maintainers", maintainer_email="maintainers@example.com",
    description="Recorded stereo mapping tools for development", license="UNLICENSED",
)

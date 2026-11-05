import hashlib
import json
from pathlib import Path
import runpy
import struct
import tempfile
import unittest
from aihub_server.firmware_release import inspect_application, install_metadata


def application():
    data=bytearray(336);data[0]=0xe9;data[1]=1;data[3]=0x40;data[23]=1
    struct.pack_into('<H',data,12,9);struct.pack_into('<II',data,24,0x3c190020,256)
    struct.pack_into('<I',data,32,0xabcd5432);data[48:52]=b'test';data[80:87]=b'xiaozhi'
    value=0xef
    for byte in data[32:288]:value^=byte
    data[303]=value;data[304:]=hashlib.sha256(data[:304]).digest()
    return bytes(data)


class FirmwareReleaseTests(unittest.TestCase):
    def test_valid_image_and_corruption(self):
        raw=application();self.assertEqual(inspect_application(raw)['version'],'test')
        for offset in (0,12,50,303,335):
            changed=bytearray(raw);changed[offset]^=1
            with self.assertRaises(ValueError):inspect_application(changed)

    def test_metadata_requires_explicit_hardware_validation_state(self):
        value={'board':'echoear-s3','partition_bytes':3072,'partition_sha256':'a'*64,'upgrade_from_sha256':['b'*64]}
        self.assertIsNone(install_metadata({'install':value}))
        value['validated']=False
        self.assertFalse(install_metadata({'install':value})['validated'])

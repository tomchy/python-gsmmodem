#!/usr/bin/env python

""" Test suite for gsmmodem.modem """

from __future__ import print_function

import sys, time, unittest, logging, codecs
from datetime import datetime
from copy import copy

from . import compat # For Python 2.6 compatibility
from gsmmodem.exceptions import PinRequiredError, CommandError, InvalidStateException, TimeoutException,\
    CmsError, CmeError, EncodingError
from gsmmodem.modem import StatusReport, Sms, ReceivedSms

PYTHON_VERSION = sys.version_info[0]

import gsmmodem.serial_comms
import gsmmodem.modem
import gsmmodem.pdu
from gsmmodem.util import SimpleOffsetTzInfo

from . import fakemodems

# Silence logging exceptions
logging.raiseExceptions = False
if sys.version_info[0] == 3 and sys.version_info[1] >= 1:
    logging.getLogger('gsmmodem').addHandler(logging.NullHandler())

# The fake modem to use (if any)
FAKE_MODEM = None
# Write callback to use during Serial.__init__() - usually None, but useful for setting write callbacks during modem.connect()
SERIAL_WRITE_CALLBACK_FUNC = None

class MockSerialPackage(object):
    """ Fake serial package for the GsmModem/SerialComms classes to import during tests """

    class Serial():

        _REPONSE_TIME = 0.02

        """ Mock serial object for use by the GsmModem class during tests """
        def __init__(self, *args, **kwargs):
            # The default value to read/"return" if responseSequence isn't set up, or None for nothing
            #self.defaultResponse = 'OK\r\n'
            self.responseSequence = []
            self.flushResponseSequence = True
            self.writeQueue = []
            self._alive = True
            self._readQueue = []
            global SERIAL_WRITE_CALLBACK_FUNC
            self.writeCallbackFunc = SERIAL_WRITE_CALLBACK_FUNC
            global FAKE_MODEM
            # Pre-determined responses to specific commands - used for imitating specific modems
            if FAKE_MODEM != None:
                self.modem = copy(FAKE_MODEM)
            else:
                self.modem = fakemodems.GenericTestModem()

        def read(self, timeout=None):
            if len(self._readQueue) > 0:
                return self._readQueue.pop(0)
            elif len(self.writeQueue) > 0:
                self._setupReadValue(self.writeQueue.pop(0))
                if len(self._readQueue) > 0:
                    return self._readQueue.pop(0)
            elif self.flushResponseSequence and len(self.responseSequence) > 0:
                self._setupReadValue(None)

            if timeout != None:
                time.sleep(0.001)
                return ''
            else:
                while self._alive:
                    if len(self.writeQueue) > 0:
                        self._setupReadValue(self.writeQueue.pop(0))
                        if len(self._readQueue) > 0:
                            return self._readQueue.pop(0)
                    time.sleep(0.05)

        def _setupReadValue(self, command):
            if len(self._readQueue) == 0:
                if len(self.responseSequence) > 0:
                    value = self.responseSequence.pop(0)
                    if type(value) in (float, int):
                        time.sleep(value)
                        if len(self.responseSequence) > 0:
                            self._setupReadValue(command)
                    else:
                        self._readQueue = list(value)
                else:
                    self.responseSequence = self.modem.getResponse(command)
                    if len(self.responseSequence) > 0:
                        self._setupReadValue(command)
                #elif command in self.modem.responses:
                #    self.responseSequence = self.modem.responses[command]
                #    if len(self.responseSequence) > 0:
                #        self._setupReadValue(command)
                #elif self.defaultResponse != None:
                #    self._readQueue = list(self.defaultResponse)

        def write(self, data):
            if self.writeCallbackFunc != None:
                self.writeCallbackFunc(data)
            self.writeQueue.append(data)

        def close(self):
            pass

        def inWaiting(self):
            rqLen = len(self._readQueue)
            for item in self.responseSequence:
                if type(item) in (int, float):
                    break
                else:
                    rqLen += len(item)
            return rqLen


    class SerialException(Exception):
        """ Mock Serial Exception """
class TestEdgeCases(unittest.TestCase):
    """ Edge-case testing; some modems do funny things during seemingly normal operations """

    def test_smscPreloaded(self):
        """ Tests reading the SMSC number if it was pre-loaded on the SIM (some modems delete the number during connect()) """
        tests = [None, '+12345678']
        global FAKE_MODEM
        for test in tests:
            for fakeModem in fakemodems.createModems():
                # Init modem and preload SMSC number
                fakeModem.smscNumber = test
                fakeModem.simBusyErrorCounter = 3 # Enable "SIM busy" errors for modem for more accurate testing
                FAKE_MODEM = fakeModem
                mockSerial = MockSerialPackage()
                gsmmodem.serial_comms.serial = mockSerial
                modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --')
                modem.connect()
                # Make sure SMSC number was prevented from being deleted (some modems do this when setting text-mode paramters AT+CSMP)
                self.assertEqual(test, modem.smsc, 'SMSC number was changed/deleted during connect()')
                modem.close()
        FAKE_MODEM = None

    def test_cfun0(self):
        """ Tests case where a modem's functionality setting is 0 at startup """
        global FAKE_MODEM
        for fakeModem in fakemodems.createModems():
            fakeModem.cfun = 0
            FAKE_MODEM = fakeModem
            # This should pass without any problem, and AT+CFUN=1 should be set during connect()
            cfunWritten = [False]
            def writeCallbackFunc(data):
                if data == 'AT+CFUN=1\r':
                    cfunWritten[0] = True
            global SERIAL_WRITE_CALLBACK_FUNC
            SERIAL_WRITE_CALLBACK_FUNC = writeCallbackFunc
            mockSerial = MockSerialPackage()
            gsmmodem.serial_comms.serial = mockSerial
            modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --')
            modem.connect()
            SERIAL_WRITE_CALLBACK_FUNC = None
            self.assertTrue(cfunWritten[0], 'Modem CFUN setting not set to 1 during connect()')
            modem.close()
            FAKE_MODEM = None

    def test_cfunNotSupported(self):
        """ Tests case where a modem does not support the AT+CFUN command """
        global FAKE_MODEM
        FAKE_MODEM = copy(fakemodems.GenericTestModem())
        FAKE_MODEM.cfun = -1 # disable
        FAKE_MODEM.responses['AT+CFUN?\r'] = ['ERROR\r\n']
        FAKE_MODEM.responses['AT+CFUN=1\r'] = ['ERROR\r\n']
        # This should pass without any problem, and AT+CFUN? should at least have been checked during connect()
        cfunWritten = [False]
        def writeCallbackFunc(data):
            if data == 'AT+CFUN?\r':
                cfunWritten[0] = True
        global SERIAL_WRITE_CALLBACK_FUNC
        SERIAL_WRITE_CALLBACK_FUNC = writeCallbackFunc
        mockSerial = MockSerialPackage()
        gsmmodem.serial_comms.serial = mockSerial
        modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --')
        modem.connect()
        SERIAL_WRITE_CALLBACK_FUNC = None
        self.assertTrue(cfunWritten[0], 'Modem CFUN setting not set to 1 during connect()')
        modem.close()
        FAKE_MODEM = None

    def test_commandNotSupported(self):
        """ Some Huawei modems response with "COMMAND NOT SUPPORT" instead of "ERROR" or "OK"; ensure we detect this """
        global FAKE_MODEM
        FAKE_MODEM = copy(fakemodems.GenericTestModem())
        FAKE_MODEM.responses['AT+WIND?\r'] = ['COMMAND NOT SUPPORT\r\n']
        mockSerial = MockSerialPackage()
        gsmmodem.serial_comms.serial = mockSerial
        modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --')
        modem.connect()
        self.assertRaises(CommandError, modem.write, 'AT+WIND?')
        modem.close()
        FAKE_MODEM = None

    def test_wavecomConnectSpecifics(self):
        """ Wavecom-specific test cases that might not be covered by the modem profiles in fakemodems.py
        - this is mostly to attain 100% code coverage in tests
        """
        global FAKE_MODEM
        FAKE_MODEM = copy(fakemodems.WavecomMultiband900E1800())
        # Test the case where AT+CLAC returns a response for Wavecom devices, and it includes +WIND and +VTS
        FAKE_MODEM.responses['AT+CLAC\r'] = ['+CLAC: D,+CUSD,+WIND,+VTS\r\n', 'OK\r\n']
        # Test the case where the +WIND setting is already what we want it to be
        FAKE_MODEM.responses['AT+WIND?\r'] = ['+WIND: 50\r\n', 'OK\r\n']
        mockSerial = MockSerialPackage()
        gsmmodem.serial_comms.serial = mockSerial
        modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --')
        modem.connect()
        self.assertTrue(gsmmodem.modem.Call.dtmfSupport, '+VTS in AT+CLAC response should have indicated DTMF support')
        modem.close()
        FAKE_MODEM = None

    def test_zteConnectSpecifics(self):
        """ ZTE-specific test cases that might not be covered by the modem profiles in fakemodems.py
        - this is mostly to attain 100% code coverage in tests
        """
        global FAKE_MODEM
        FAKE_MODEM = copy(fakemodems.ZteK3565Z())
        # Test the case where AT+CLAC returns a response for ZTE devices, and it includes +ZPAS and +VTS
        FAKE_MODEM.responses['AT+CLAC\r'][-1] = '+ZPAS\r\n'
        FAKE_MODEM.responses['AT+CLAC\r'].append('OK\r\n')
        mockSerial = MockSerialPackage()
        gsmmodem.serial_comms.serial = mockSerial
        modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --')
        modem.connect()
        self.assertTrue(gsmmodem.modem.Call.dtmfSupport, '+VTS in AT+CLAC response should have indicated DTMF support')
        modem.close()
        FAKE_MODEM = None

    def test_huaweiConnectSpecifics(self):
        """ Huawei-specific test cases that might not be covered by the modem profiles in fakemodems.py
        - this is mostly to attain 100% code coverage in tests
        """
        global FAKE_MODEM
        FAKE_MODEM = copy(fakemodems.HuaweiK3715())
        # Test the case where AT+CLAC returns no response for Huawei devices; causing the need for other methods to detect phone type
        FAKE_MODEM.responses['AT+CLAC\r'] = ['ERROR\r\n']
        mockSerial = MockSerialPackage()
        gsmmodem.serial_comms.serial = mockSerial
        modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --')
        modem.connect()
        # Huawei modems should have DTMF support
        self.assertTrue(gsmmodem.modem.Call.dtmfSupport, 'Huawei modems should have DTMF support')
        modem.close()
        FAKE_MODEM = None

    def test_smscSpecifiedBeforeConnect(self):
        """ Tests connect() operation when an SMSC number is set before connect() is called """
        smscNumber = '123454321'
        global FAKE_MODEM
        FAKE_MODEM = copy(fakemodems.GenericTestModem())
        FAKE_MODEM.smsc = None
        mockSerial = MockSerialPackage()
        gsmmodem.serial_comms.serial = mockSerial
        modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --')
        # Look for the AT+CSCA write
        cscaWritten = [False]
        def writeCallbackFunc(data):
            if data == 'AT+CSCA="{0}"\r'.format(smscNumber):
                cscaWritten[0] = True
        global SERIAL_WRITE_CALLBACK_FUNC
        SERIAL_WRITE_CALLBACK_FUNC = writeCallbackFunc
        # Set the SMSC number before calling connect()
        modem.smsc = smscNumber
        self.assertFalse(cscaWritten[0])
        modem.connect()
        self.assertTrue(cscaWritten[0], 'Preset SMSC value not written to modem during connect()')
        self.assertEqual(modem.smsc, smscNumber, 'Pre-set SMSC not stored correctly during connect()')
        modem.close()
        FAKE_MODEM = None

    def test_cpmsNotSupported(self):
        """ Tests case where a modem does not support the AT+CPMS command """
        global FAKE_MODEM
        FAKE_MODEM = copy(fakemodems.GenericTestModem())
        FAKE_MODEM.responses['AT+CPMS=?\r'] = ['+CMS ERROR: 302\r\n']
        # This should pass without any problem, and AT+CPMS=? should at least have been checked during connect()
        cpmsWritten = [False]
        def writeCallbackFunc(data):
            if data == 'AT+CPMS=?\r':
                cpmsWritten[0] = True
        global SERIAL_WRITE_CALLBACK_FUNC
        SERIAL_WRITE_CALLBACK_FUNC = writeCallbackFunc
        mockSerial = MockSerialPackage()
        gsmmodem.serial_comms.serial = mockSerial
        modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --')
        modem.connect()
        SERIAL_WRITE_CALLBACK_FUNC = None
        self.assertTrue(cpmsWritten[0], 'Modem CPMS allowed values not checked during connect()')
        modem.close()
        FAKE_MODEM = None

    def test_cnmiNotSupported(self):
        """ Tests case where a modem does not support the AT+CNMI command (but does support other SMS-related commands) """
        global FAKE_MODEM
        FAKE_MODEM = copy(fakemodems.GenericTestModem())
        FAKE_MODEM.responses['AT+CNMI=2,1,0,2\r'] = ['ERROR\r\n']
        FAKE_MODEM.responses['AT+CNMI=2,1,0,1,0\r'] = ['ERROR\r\n']
        # This should pass without any problem, and AT+CNMI=2,1,0,2 should at least have been attempted during connect()
        cnmiWritten = [False]
        def writeCallbackFunc(data):
            if data == 'AT+CNMI=2,1,0,2\r':
                cnmiWritten[0] = True
        global SERIAL_WRITE_CALLBACK_FUNC
        SERIAL_WRITE_CALLBACK_FUNC = writeCallbackFunc
        mockSerial = MockSerialPackage()
        gsmmodem.serial_comms.serial = mockSerial
        modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --')
        modem.connect()
        SERIAL_WRITE_CALLBACK_FUNC = None
        self.assertTrue(cnmiWritten[0], 'AT+CNMI setting not written to modem during connect()')
        self.assertFalse(modem._smsReadSupported, 'Modem\'s internal SMS read support flag should be False if AT+CNMI is not supported')
        modem.close()
        FAKE_MODEM = None

    def test_clipNotSupported(self):
        """ Tests case where a modem does not support the AT+CLIP command """
        global FAKE_MODEM
        FAKE_MODEM = copy(fakemodems.GenericTestModem())
        FAKE_MODEM.responses['AT+CLIP=1\r'] = ['ERROR\r\n']
        # This should pass without any problem, and AT+CLIP=1 should at least have been attempted during connect()
        clipWritten = [False]
        crcWritten = [False]
        def writeCallbackFunc(data):
            if data == 'AT+CLIP=1\r':
                clipWritten[0] = True
            elif data == 'AT+CRC=1\r':
                crcWritten[0] = True
        global SERIAL_WRITE_CALLBACK_FUNC
        SERIAL_WRITE_CALLBACK_FUNC = writeCallbackFunc
        mockSerial = MockSerialPackage()
        gsmmodem.serial_comms.serial = mockSerial
        modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --')
        modem.connect()
        SERIAL_WRITE_CALLBACK_FUNC = None
        self.assertTrue(clipWritten[0], 'AT+CLIP=1 not written to modem during connect()')
        self.assertFalse(crcWritten[0], 'AT+CRC=1 should not be attempted if AT+CLIP is not supported')
        self.assertFalse(modem._callingLineIdentification, 'Modem\'s internal calling line identification flag should be False if AT+CLIP is not supported')
        self.assertFalse(modem._extendedIncomingCallIndication, 'Modem\'s internal extended calling line identification information flag should be False if AT+CLIP is not supported')
        modem.close()
        FAKE_MODEM = None

    def test_crcNotSupported(self):
        """ Tests case where a modem does not support the AT+CRC command """
        global FAKE_MODEM
        FAKE_MODEM = copy(fakemodems.GenericTestModem())
        FAKE_MODEM.responses['AT+CRC=1\r'] = ['ERROR\r\n']
        # This should pass without any problem, and AT+CRC=1 should at least have been attempted during connect()
        clipWritten = [False]
        crcWritten = [False]
        def writeCallbackFunc(data):
            if data == 'AT+CLIP=1\r':
                clipWritten[0] = True
            elif data == 'AT+CRC=1\r':
                crcWritten[0] = True
        global SERIAL_WRITE_CALLBACK_FUNC
        SERIAL_WRITE_CALLBACK_FUNC = writeCallbackFunc
        mockSerial = MockSerialPackage()
        gsmmodem.serial_comms.serial = mockSerial
        modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --')
        modem.connect()
        SERIAL_WRITE_CALLBACK_FUNC = None
        self.assertTrue(clipWritten[0], 'AT+CLIP=1 not written to modem during connect()')
        self.assertTrue(crcWritten[0], 'AT+CRC=1 not written to modem during connect()')
        self.assertTrue(modem._callingLineIdentification, 'Modem\'s internal calling line identification flag should be True if AT+CLIP is supported')
        self.assertFalse(modem._extendedIncomingCallIndication, 'Modem\'s internal extended calling line identification information flag should be False if AT+CRC is not supported')
        modem.close()
        FAKE_MODEM = None

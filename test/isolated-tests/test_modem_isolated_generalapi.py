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


class TestGsmModemGeneralApi(unittest.TestCase):
    """ Tests the API of GsmModem class (excluding connect/close) """

    def setUp(self):
        # Override the pyserial import
        self.mockSerial = MockSerialPackage()
        gsmmodem.serial_comms.serial = self.mockSerial
        self.modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --')
        self.modem.connect()

    def tearDown(self):
        self.modem.close()

    def test_manufacturer(self):
        def writeCallbackFunc(data):
            if type(data) == bytes:
                data = data.decode()
            self.assertEqual('AT+CGMI\r', data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CGMI\r', data))
        self.modem.serial.writeCallbackFunc = writeCallbackFunc
        tests = ['huawei', 'ABCDefgh1235', 'Some Random Manufacturer']
        for test in tests:
            self.modem.serial.responseSequence = ['{0}\r\n'.format(test), 'OK\r\n']
            self.assertEqual(test, self.modem.manufacturer)

    def test_model(self):
        def writeCallbackFunc(data):
            if type(data) == bytes:
                data = data.decode()
            self.assertEqual('AT+CGMM\r', data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CGMM\r', data))
        self.modem.serial.writeCallbackFunc = writeCallbackFunc
        tests = ['K3715', '1324-Qwerty', 'Some Random Model']
        for test in tests:
            self.modem.serial.responseSequence = ['{0}\r\n'.format(test), 'OK\r\n']
            self.assertEqual(test, self.modem.model)

    def test_revision(self):
        def writeCallbackFunc(data):
            if type(data) == bytes:
                data = data.decode()
            self.assertEqual('AT+CGMR\r', data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CGMR\r', data))
        self.modem.serial.writeCallbackFunc = writeCallbackFunc
        tests = ['1', '1324-56768-23414', 'r987']
        for test in tests:
            self.modem.serial.responseSequence = ['{0}\r\n'.format(test), 'OK\r\n']
            self.assertEqual(test, self.modem.revision)
        # Fake a modem that does not support this command
        self.modem.serial.modem.defaultResponse = ['ERROR\r\n']
        self.assertEqual(None, self.modem.revision)

    def test_imei(self):
        def writeCallbackFunc(data):
            if type(data) == bytes:
                data = data.decode()
            self.assertEqual('AT+CGSN\r', data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CGSN\r', data))
        self.modem.serial.writeCallbackFunc = writeCallbackFunc
        tests = ['012345678912345']
        for test in tests:
            self.modem.serial.responseSequence = ['{0}\r\n'.format(test), 'OK\r\n']
            self.assertEqual(test, self.modem.imei)

    def test_imsi(self):
        def writeCallbackFunc(data):
            if type(data) == bytes:
                data = data.decode()
            self.assertEqual('AT+CIMI\r', data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CIMI\r', data))
        self.modem.serial.writeCallbackFunc = writeCallbackFunc
        tests = ['987654321012345']
        for test in tests:
            self.modem.serial.responseSequence = ['{0}\r\n'.format(test), 'OK\r\n']
            self.assertEqual(test, self.modem.imsi)

    def test_networkName(self):
        def writeCallbackFunc(data):
            if type(data) == bytes:
                data = data.decode()
            self.assertEqual('AT+COPS?\r', data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+COPS', data))
        self.modem.serial.writeCallbackFunc = writeCallbackFunc
        tests = [('MTN', '+COPS: 0,0,"MTN",2'),
                 ('I OMNITEL', '+COPS: 0,0,"I OMNITEL"'),
                 (None, 'SOME RANDOM RESPONSE')]
        for name, toWrite in tests:
            self.modem.serial.responseSequence = ['{0}\r\n'.format(toWrite), 'OK\r\n']
            self.assertEqual(name, self.modem.networkName)

    def test_supportedCommands(self):
        def writeCallbackFunc(data):
            if type(data) == bytes:
                data = data.decode()
            if data == 'AT\r':
                return
            self.assertEqual('AT+CLAC\r', data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CLAC\r', data))
        self.modem.serial.writeCallbackFunc = writeCallbackFunc
        tests = ((['+CLAC:&C,D,E,\S,+CGMM,^DTMF\r\n', 'OK\r\n'], ['&C', 'D', 'E', '\S', '+CGMM', '^DTMF']),
                 (['+CLAC:Z\r\n', 'OK\r\n'], ['Z']),
                 (['FGH,RTY,UIO\r\n', 'OK\r\n'], ['FGH', 'RTY', 'UIO']), # nasty, but possible
                 # ZTE-like response: do not start with +CLAC, and use multiple lines
                 (['A\r\n', 'BCD\r\n', 'EFGH\r\n', 'OK\r\n'], ['A', 'BCD', 'EFGH']),
                 # Some Huawei modems have a ZTE-like response, but add an addition \r character at the end of each listed command
                 (['Q\r\r\n', 'QWERTY\r\r\n', '^DTMF\r\r\n', 'OK\r\n'], ['Q', 'QWERTY', '^DTMF']))
        for responseSequence, expected in tests:
            self.modem.serial.responseSequence = responseSequence
            commands = self.modem.supportedCommands
            self.assertEqual(commands, expected)
        # Fake a modem that does not support this command
        self.modem.serial.responseSequence = ['ERROR\r\n']
        commands = self.modem.supportedCommands
        self.assertEqual(commands, None)
        # Test unhandled response format
        self.modem.serial.responseSequence = ['OK\r\n']
        commands = self.modem.supportedCommands
        self.assertEqual(commands, None)

    def test_smsc(self):
        """ Tests reading and writing the SMSC number from the SIM card """
        def writeCallbackFunc1(data):
            if type(data) == bytes:
                data = data.decode()
            self.assertEqual('AT+CSCA?\r', data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CSCA?', data))
        self.modem.serial.writeCallbackFunc = writeCallbackFunc1
        tests = [None, '+12345678']
        for test in tests:
            if test:
                self.modem.serial.responseSequence = ['+CSCA: "{0}",145\r\n'.format(test), 'OK\r\n']
            else:
                self.modem.serial.responseSequence = ['OK\r\n']
            self.assertEqual(test, self.modem.smsc)
        # Reset SMSC number internally
        self.modem._smscNumber = None
        self.assertEqual(self.modem.smsc, None)
        # Now test setting the SMSC number
        for test in tests:
            if not test:
                continue
            def writeCallbackFunc2(data):
                if type(data) == bytes:
                    data = data.decode()
                self.assertEqual('AT+CSCA="{0}"\r'.format(test), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CSCA="{0}"'.format(test), data))
            def writeCallbackFunc3(data):
                if type(data) == bytes:
                    data = data.decode()
                # This method should not be called - it merely exists to make sure nothing is written to the modem
                self.fail("Nothing should have been written to modem, but got: {0}".format(data))
            self.modem.serial.writeCallbackFunc = writeCallbackFunc2
            self.modem.smsc = test
            self.assertEqual(test, self.modem.smsc)
            # Now see if the SMSC value was cached properly
            self.modem.serial.writeCallbackFunc = writeCallbackFunc3
            self.assertEqual(test, self.modem.smsc)
            self.modem.smsc = test # Shouldn't do anything
        # Check response if modem returns a +CMS ERROR: 330 (SMSC number unknown) on querying the SMSC
        self.modem._smscNumber = None
        self.modem.serial.responseSequence = ['+CMS ERROR: 330\r\n']
        self.modem.serial.writeCallbackFunc = writeCallbackFunc1
        self.assertEqual(self.modem.smsc, None) # Should just return None

    def test_signalStrength(self):
        """ Tests reading signal strength from the modem """
        def writeCallbackFunc(data):
            if type(data) == bytes:
                data = data.decode()
            self.assertEqual('AT+CSQ\r', data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CSQ', data))
        self.modem.serial.writeCallbackFunc = writeCallbackFunc
        tests = (('+CSQ: 18,99', 18),
                 ('+CSQ:4,0', 4),
                 ('+CSQ: 99,99', -1))
        for response, expected in tests:
            self.modem.serial.responseSequence = ['{0}\r\n'.format(response), 'OK\r\n']
            self.assertEqual(expected, self.modem.signalStrength)
        # Test error condition (unparseable response)
        self.modem.serial.responseSequence = ['OK\r\n']
        try:
            self.modem.signalStrength
        except CommandError:
            pass
        else:
            self.fail('CommandError not raised on error condition')

    def test_waitForNetorkCoverageNoCreg(self):
        """ Tests waiting for network coverage (no AT+CREG support) """
        tests = ((82,),
                 (99, 99, 47),)
        for seq in tests:
            items = iter(seq)
            def writeCallbackFunc(data):
                if type(data) == bytes:
                    data = data.decode()
                if data == 'AT+CSQ\r':
                    try:
                        self.modem.serial.responseSequence = ['+CSQ: {0},99\r\n'.format(next(items)), 'OK\r\n']
                    except StopIteration:
                        self.fail("Too many AT+CSQ writes issued")
            self.modem.serial.writeCallbackFunc = writeCallbackFunc
            signalStrength = self.modem.waitForNetworkCoverage()
            self.assertNotEqual(signalStrength, -1, '"Unknown" signal strength returned - should still have blocked')
            self.assertEqual(seq[-1], signalStrength, 'Incorrect signal strength returned')

    def test_waitForNetorkCoverage(self):
        """ Tests waiting for network coverage (normal) """
        tests = (('0,2', '0,2', '0,1', 82),
                 ('0,5', 47),)
        for seq in tests:
            items = iter(seq)
            def writeCallbackFunc(data):
                if type(data) == bytes:
                    data = data.decode()
                if data == 'AT+CSQ\r':
                    try:
                        self.modem.serial.responseSequence = ['+CSQ: {0},99\r\n'.format(next(items)), 'OK\r\n']
                    except StopIteration:
                        self.fail("Too many writes issued")
                elif data == 'AT+CREG?\r':
                    try:
                        self.modem.serial.responseSequence = ['+CREG: {0}\r\n'.format(next(items)), 'OK\r\n']
                    except StopIteration:
                        self.fail("Too many writes issued")
            self.modem.serial.writeCallbackFunc = writeCallbackFunc
            signalStrength = self.modem.waitForNetworkCoverage()
            self.assertNotEqual(signalStrength, -1, '"Unknown" signal strength returned - should still have blocked')
            self.assertEqual(seq[-1], signalStrength, 'Incorrect signal strength returned')
        # Test InvalidStateException
        tests = ('0,3', '0,0') # 0,3: network registration denied. 0,0: SIM not searching for network
        for result in tests:
            def writeCallbackFunc(data):
                if type(data) == bytes:
                    data = data.decode()
                if data == 'AT+CREG?\r':
                    self.modem.serial.responseSequence = ['+CREG: {0}\r\n'.format(result), 'OK\r\n']
            self.modem.serial.writeCallbackFunc = writeCallbackFunc
            self.assertRaises(InvalidStateException, self.modem.waitForNetworkCoverage)
        # Test TimeoutException
        def writeCallbackFunc2(data):
            if type(data) == bytes:
                data = data.decode()
            self.modem.serial.responseSequence = ['+CREG: 0,1\r\n'.format(result), 'OK\r\n']
        self.modem.serial.writeCallbackFunc = writeCallbackFunc2
        self.assertRaises(TimeoutException, self.modem.waitForNetworkCoverage, timeout=1)

    def test_errorTypes(self):
        """ Tests error type detection- and handling by throwing random errors to commands """
        # Throw unnamed error
        self.modem.serial.responseSequence = ['ERROR\r\n']
        try:
            self.modem.write('AT')
        except CommandError as e:
            self.assertIsInstance(e, CommandError)
            self.assertEqual(e.command, 'AT')
            self.assertEqual(e.type, None)
            self.assertEqual(e.code, None)
        # Throw CME error
        self.modem.serial.responseSequence = ['+CME ERROR: 22\r\n']
        try:
            self.modem.write('AT+ZZZ')
        except CommandError as e:
            self.assertIsInstance(e, CmeError)
            self.assertEqual(e.command, 'AT+ZZZ')
            self.assertEqual(e.type, 'CME')
            self.assertEqual(e.code, 22)
        # Throw CMS error
        self.modem.serial.responseSequence = ['+CMS ERROR: 310\r\n']
        try:
            self.modem.write('AT+XYZ')
        except CommandError as e:
            self.assertIsInstance(e, CmsError)
            self.assertEqual(e.command, 'AT+XYZ')
            self.assertEqual(e.type, 'CMS')
            self.assertEqual(e.code, 310)

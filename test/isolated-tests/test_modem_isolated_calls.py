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


class TestGsmModemDial(unittest.TestCase):

    def tearDown(self):
        self.modem.close()
        global FAKE_MODEM
        FAKE_MODEM = None

    def init_modem(self, modem):
        global FAKE_MODEM
        FAKE_MODEM = modem
        self.mockSerial = MockSerialPackage()
        gsmmodem.serial_comms.serial = self.mockSerial
        self.modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --')
        self.modem.connect()

    def test_dial(self):
        """ Tests dialing without specifying a callback function """
        tests = (['0123456789', '1', '0'],)

        global MODEMS
        testModems = fakemodems.createModems()
        testModems.append(fakemodems.GenericTestModem()) # Test polling only
        for fakeModem in testModems:
            self.init_modem(fakeModem)

            modem = self.modem.serial.modem # load the copy()-ed modem instance
            print(modem)
            for number, callId, callType in tests:
                def writeCallbackFunc(data):
                    if self.modem._mustPollCallStatus and data.startswith('AT+CLCC'):
                        return # Can happen due to polling
                    self.assertEqual('ATD{0};\r'.format(number), data, 'Invalid data written to modem; expected "{0}", got: "{1}". Modem: {2}'.format('ATD{0};'.format(number), data[:-1] if data[-1] == '\r' else data, modem))
                    self.modem.serial.writeCallbackFunc = None
                self.modem.serial.writeCallbackFunc = writeCallbackFunc
                self.modem.serial.responseSequence = modem.getAtdResponse(number)
                self.modem.serial.responseSequence.extend(modem.getPreCallInitWaitSequence())
                # Fake call initiated notification
                self.modem.serial.responseSequence.extend(modem.getCallInitNotification(callId, callType))
                call = self.modem.dial(number)
                print("PASSED1")
                # Wait for the read buffer to clear
                while len(self.modem.serial._readQueue) > 0 or len(self.modem.serial.responseSequence) > 0:
                    time.sleep(0.05)
                if self.modem._mustPollCallStatus:
                    time.sleep(0.6)
                self.assertIsInstance(call, gsmmodem.modem.Call)
                self.assertIs(call.number, number)
                # Check status
                self.assertTrue(call.active, 'Call state invalid: should be active. Modem: {0}'.format(modem))
                self.assertFalse(call.answered, 'Call state invalid: should not yet be answered. Modem: {0}'.format(modem))
                self.assertIn(call.id, self.modem.activeCalls)
                self.assertEqual(len(self.modem.activeCalls), 1)
                # Fake an answer
                self.modem.serial.responseSequence = modem.getRemoteAnsweredNotification(callId, callType)
                # Wait a bit for the event to be picked up
                while len(self.modem.serial._readQueue) > 0 or len(self.modem.serial.responseSequence) > 0:
                    time.sleep(0.05)
                if self.modem._mustPollCallStatus:
                    time.sleep(0.6) # Ensure polling picks up event
                elif not self.modem._waitForCallInitUpdate:
                    time.sleep(0.1) # Ensure event is picked up
                self.assertTrue(call.answered, 'Remote call answer was not detected. Modem: {0}'.format(modem))
                self.assertTrue(call.active, 'Call state invalid: should be active. Modem: {0}'.format(modem))
                def hangupCallback(data):
                    if self.modem._mustPollCallStatus and data.startswith('AT+CLCC'):
                        return # Can happen due to polling
                    self.assertEqual('ATH\r'.format(number), data, 'Invalid data written to modem; expected "{0}", got: "{1}". Modem: {2}'.format('ATH'.format(number), data[:-1] if data[-1] == '\r' else data, modem))
                self.modem.serial.writeCallbackFunc = hangupCallback
                call.hangup()
                self.assertFalse(call.answered, 'Hangup call did not change answered state. Modem: {0}'.format(modem))
                self.assertFalse(call.active, 'Call state invalid: should not be active (local hangup). Modem: {0}'.format(modem))
                self.assertNotIn(call.id, self.modem.activeCalls)
                self.assertEqual(len(self.modem.activeCalls), 0)

                ############## Check remote hangup detection ###############
                self.modem.serial.writeCallbackFunc = writeCallbackFunc
                self.modem.serial.responseSequence = modem.getAtdResponse(number)
                self.modem.serial.responseSequence.extend(modem.getPreCallInitWaitSequence())
                # Fake call initiated notification
                self.modem.serial.responseSequence.extend(modem.getCallInitNotification(callId, callType))
                call = self.modem.dial(number)
                print("PASSED2")
                self.assertTrue(call.active, 'Call state invalid: should be active. Modem: {0}'.format(modem))
                # Wait a bit for the event to be picked up
                while len(self.modem.serial._readQueue) > 0 or len(self.modem.serial.responseSequence) > 0:
                    time.sleep(0.05)
                if self.modem._mustPollCallStatus:
                    time.sleep(0.6) # Ensure polling picks up event
                # Fake remote answer
                self.modem.serial.responseSequence = modem.getRemoteAnsweredNotification(callId, callType)
                while len(self.modem.serial._readQueue) > 0 or len(self.modem.serial.responseSequence) > 0:
                    time.sleep(0.05)
                if self.modem._mustPollCallStatus:
                    time.sleep(0.5) # Ensure polling picks up event
                elif not self.modem._waitForCallInitUpdate:
                    time.sleep(0.1) # Ensure event is picked up
                self.assertTrue(call.answered, 'Remote call answer was not detected. Modem: {0}'.format(modem))
                self.assertIn(call.id, self.modem.activeCalls)
                self.assertEqual(len(self.modem.activeCalls), 1)
                # Now fake a remote hangup
                self.modem.serial.responseSequence = modem.getRemoteHangupNotification(callId, callType)
                # Wait a bit for the event to be picked up
                while len(self.modem.serial._readQueue) > 0 or len(self.modem.serial.responseSequence) > 0:
                    time.sleep(0.05)
                if self.modem._mustPollCallStatus:
                    time.sleep(0.6) # Ensure polling picks up event
                self.assertFalse(call.answered, 'Remote hangup was not detected. Modem: {0}'.format(modem))
                self.assertFalse(call.active, 'Call state invalid: should not be active (remote hangup). Modem: {0}'.format(modem))
                self.assertNotIn(call.id, self.modem.activeCalls)
                self.assertEqual(len(self.modem.activeCalls), 0)

                ############## Check remote call rejection (hangup before answering) ###############
                self.modem.serial.writeCallbackFunc = writeCallbackFunc
                self.modem.serial.responseSequence = modem.getAtdResponse(number)
                self.modem.serial.responseSequence.extend(modem.getPreCallInitWaitSequence())
                # Fake call initiated notification
                self.modem.serial.responseSequence.extend(modem.getCallInitNotification(callId, callType))
                call = self.modem.dial(number)
                print("PASSED3")
                self.assertTrue(call.active, 'Call state invalid: should be active. Modem: {0}'.format(modem))
                # Wait a bit for the event to be picked up
                while len(self.modem.serial._readQueue) > 0 or len(self.modem.serial.responseSequence) > 0:
                    time.sleep(0.05)
                if self.modem._mustPollCallStatus:
                    time.sleep(0.6) # Ensure polling picks up event
                self.assertFalse(call.answered, 'Call should not have been in "answered" state. Modem: {0}'.format(modem))
                self.assertIn(call.id, self.modem.activeCalls)
                self.assertEqual(len(self.modem.activeCalls), 1)
                # Now reject the call
                self.modem.serial.responseSequence = modem.getRemoteRejectCallNotification(callId, callType)
                # Wait a bit for the event to be picked up
                while len(self.modem.serial._readQueue) > 0 or len(self.modem.serial.responseSequence) > 0:
                    time.sleep(0.05)
                if self.modem._mustPollCallStatus:
                    time.sleep(0.6) # Ensure polling picks up event
                time.sleep(0.05)
                self.assertFalse(call.answered, 'Call state invalid: should not be answered (remote call rejection). Modem: {0}'.format(modem))
                self.assertFalse(call.active, 'Call state invalid: should not be active (remote rejection). Modem: {0}'.format(modem))
                self.assertNotIn(call.id, self.modem.activeCalls)
                self.assertEqual(len(self.modem.activeCalls), 0)
            self.modem.close()

if __name__ == "__main__":
    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.DEBUG)
    unittest.main()

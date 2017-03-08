#!/usr/bin/env python
# -*- coding: utf8 -*-

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
            if type(data) == bytes:
                data = data.decode()
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


class TestSms(unittest.TestCase):
    """ Tests the SMS API of GsmModem class """

    def setUp(self):
        self.tests = (('+0123456789', 'Hello world!',
                       1,
                       datetime(2013, 3, 8, 15, 2, 16, tzinfo=SimpleOffsetTzInfo(2)),
                       '+2782913593',
                       '06917228195339040A9110325476980000313080512061800CC8329BFD06DDDF72363904', 29, 142,
                       'SM'),
                      ('+9876543210',
                       'Hallo\nhoe gaan dit?',
                       4,
                       datetime(2013, 3, 8, 15, 2, 16, tzinfo=SimpleOffsetTzInfo(2)),
                       '+2782913593',
                       '06917228195339040A91896745230100003130805120618013C8309BFD56A0DF65D0391C7683C869FA0F', 35, 33,
                       'SM'),
                      ('+353870000000', 'My message',
                       13,
                       datetime(2013, 4, 20, 20, 22, 27, tzinfo=SimpleOffsetTzInfo(4)),
                       None, None, 0, 0, 'ME'),
                      )
        # address_text data to use for tests when testing PDU mode
        self.testsPduAddressText = ('', '"abc123"', '""', 'Test User 123', '9876543231')

    def initModem(self, smsReceivedCallbackFunc):
        # Override the pyserial import
        self.mockSerial = MockSerialPackage()
        gsmmodem.serial_comms.serial = self.mockSerial
        self.modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --', smsReceivedCallbackFunc=smsReceivedCallbackFunc)
        self.modem.connect()

    def test_sendSmsLeaveTextModeOnInvalidCharacter(self):
        """ Tests sending SMS messages in text mode """
        self.initModem(None)
        self.modem.smsTextMode = True # Set modem to text mode
        self.assertTrue(self.modem.smsTextMode)
        # PDUs checked on https://www.diafaan.com/sms-tutorials/gsm-modem-tutorial/online-sms-pdu-decoder/
        tests = (('+0123456789', 'Helló worłd!',
                  1,
                  datetime(2013, 3, 8, 15, 2, 16, tzinfo=SimpleOffsetTzInfo(2)),
                  '+2782913593',
                  [('00218D0A91103254769800081800480065006C006C00F300200077006F0072014200640021', 36, 141)],
                  'SM',
                  'UCS2'),
                 ('+0123456789', 'Hellò wor£d!',
                  2,
                  datetime(2013, 3, 8, 15, 2, 16, tzinfo=SimpleOffsetTzInfo(2)),
                  '82913593',
                  [('00218E0A91103254769800000CC8329B8D00DDDFF2003904', 23, 142)],
                  'SM',
                  'GSM'),
                 ('+0123456789', '12345-010 12345-020 12345-030 12345-040 12345-050 12345-060 12345-070 12345-080 12345-090 12345-100 12345-110 12345-120 12345-130 12345-140 12345-150 12345-160-Hellò wor£d!',
                  3,
                  datetime(2013, 3, 8, 15, 2, 16, tzinfo=SimpleOffsetTzInfo(2)),
                  '82913593',
                  [('00618F0A9110325476980000A00500038F020162B219ADD682C560A0986C46ABB560321828269BD16A2DD80C068AC966B45A0B46838162B219ADD682D560A0986C46ABB560361828269BD16A2DD80D068AC966B45A0B86838162B219ADD682E560A0986C46ABB562301828269BD16AAD580C068AC966B45A2B26838162B219ADD68ACD60A0986C46ABB562341828269BD16AAD580D068AC966', 152, 143),
('00618F0A91103254769800001A0500038F020268B556CC066B21CB6C3602747FCB03E410', 35, 143)],
                  'SM',
                  'GSM'),
                 ('+0123456789', 'Hello world!\n Hello world!\n Hello world!\n Hello world!\n-> Helló worłd! ',
                  4,
                  datetime(2013, 3, 8, 15, 2, 16, tzinfo=SimpleOffsetTzInfo(2)),
                  '+2782913593',
                  [('0061900A91103254769800088C05000390020100480065006C006C006F00200077006F0072006C00640021000A002000480065006C006C006F00200077006F0072006C00640021000A002000480065006C006C006F00200077006F0072006C00640021000A002000480065006C006C006F00200077006F0072006C00640021000A002D003E002000480065006C006C00F300200077006F0072', 152, 144),
                   ('0061900A91103254769800080E0500039002020142006400210020', 26, 144)],
                  'SM',
                  'UCS2'),)

        for number, message, index, smsTime, smsc, pdus, mem, encoding in tests:
            def writeCallbackFunc(data):
                def writeCallbackFunc2(data):
                    # Second step - get available encoding schemes
                    self.assertEqual('AT+CSCS=?\r', data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CSCS=?', data))
                    self.modem.serial.writeCallbackFunc = writeCallbackFunc3

                def writeCallbackFunc3(data):
                    # Third step - set encoding
                    self.assertEqual('AT+CSCS="{0}"\r'.format(encoding), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CSCS="{0}"\r'.format(encoding), data))
                    self.modem.serial.writeCallbackFunc = writeCallbackFunc4

                def writeCallbackFunc4(data):
                    # Fourth step - send PDU length
                    tpdu_length = pdus[self.currentPdu][1]
                    ref = pdus[self.currentPdu][2]
                    self.assertEqual('AT+CMGS={0}\r'.format(tpdu_length), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGS={0}'.format(tpdu_length), data))
                    self.modem.serial.writeCallbackFunc = writeCallbackFunc5
                    self.modem.serial.flushResponseSequence = False
                    self.modem.serial.responseSequence = ['> \r\n', '+CMGS: {0}\r\n'.format(ref), 'OK\r\n']

                def writeCallbackFuncRaiseError(data):
                    self.assertEqual(self.currentPdu, len(pdus) - 1, 'Invalid data written to modem; expected {0} PDUs, got {1} PDU'.format(len(pdus), self.currentPdu + 1))

                def writeCallbackFunc5(data):
                    # Fifth step - send SMS PDU
                    pdu = pdus[self.currentPdu][0]
                    self.assertEqual('{0}{1}'.format(pdu, chr(26)), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('{0}{1}'.format(pdu, chr(26)), data))
                    self.modem.serial.flushResponseSequence = True
                    self.currentPdu += 1
                    if len(pdus) > self.currentPdu:
                        self.modem.serial.writeCallbackFunc = writeCallbackFunc4
                    else:
                        self.modem.serial.writeCallbackFunc = writeCallbackFuncRaiseError

                # First step - change to PDU mode
                self.assertEqual('AT+CMGF=0\r', data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGF=0', data))
                self.modem.serial.writeCallbackFunc = writeCallbackFunc2
                self.currentPdu = 0
                self.modem._smsRef = pdus[self.currentPdu][2]

            self.modem.serial.writeCallbackFunc = writeCallbackFunc
            self.modem.serial.flushResponseSequence = True
            sms = self.modem.sendSms(number, message)
            self.assertFalse(self.modem.smsTextMode)
            self.assertEqual(self.modem._smsEncoding, encoding, 'Modem uses invalid encoding. Expected "{0}", got "{1}"'.format(encoding, self.modem._smsEncoding))
            self.assertIsInstance(sms, gsmmodem.modem.SentSms)
            self.assertEqual(sms.number, number, 'Sent SMS has invalid number. Expected "{0}", got "{1}"'.format(number, sms.number))
            self.assertEqual(sms.text, message, 'Sent SMS has invalid text. Expected "{0}", got "{1}"'.format(message, sms.text))
            self.assertIsInstance(sms.reference, int, 'Sent SMS reference type incorrect. Expected "{0}", got "{1}"'.format(int, type(sms.reference)))
            ref = pdus[0][2] # All refference numbers should be equal
            self.assertEqual(sms.reference, ref, 'Sent SMS reference incorrect. Expected "{0}", got "{1}"'.format(ref, sms.reference))
            self.assertEqual(sms.status, gsmmodem.modem.SentSms.ENROUTE, 'Sent SMS status should have been {0} ("ENROUTE"), but is: {1}'.format(gsmmodem.modem.SentSms.ENROUTE, sms.status))
            # Reset mode and encoding
            self.modem._smsTextMode = True # Set modem to text mode
            self.modem._smsEncoding = "GSM" # Set encoding to GSM-7
            self.modem._smsSupportedEncodingNames = None # Force modem to ask about possible encoding names
        self.modem.close()

    def test_sendSmsTextMode(self):
        """ Tests sending SMS messages in text mode """
        self.initModem(None)
        self.modem.smsTextMode = True # Set modem to text mode
        self.assertTrue(self.modem.smsTextMode)
        for number, message, index, smsTime, smsc, pdu, tpdu_length, ref, mem in self.tests:
            self.modem._smsRef = ref
            def writeCallbackFunc(data):
                def writeCallbackFunc2(data):
                    self.assertEqual('{0}{1}'.format(message, chr(26)), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('{0}{1}'.format(message, chr(26)), data))
                    self.modem.serial.flushResponseSequence = True
                self.assertEqual('AT+CMGS="{0}"\r'.format(number), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGS="{0}"'.format(number), data))
                self.modem.serial.writeCallbackFunc = writeCallbackFunc2
            self.modem.serial.writeCallbackFunc = writeCallbackFunc
            self.modem.serial.flushResponseSequence = False
            self.modem.serial.responseSequence = ['> \r\n', '+CMGS: {0}\r\n'.format(ref), 'OK\r\n']
            sms = self.modem.sendSms(number, message)
            self.assertIsInstance(sms, gsmmodem.modem.SentSms)
            self.assertEqual(sms.number, number, 'Sent SMS has invalid number. Expected "{0}", got "{1}"'.format(number, sms.number))
            self.assertEqual(sms.text, message, 'Sent SMS has invalid text. Expected "{0}", got "{1}"'.format(message, sms.text))
            self.assertIsInstance(sms.reference, int, 'Sent SMS reference type incorrect. Expected "{0}", got "{1}"'.format(int, type(sms.reference)))
            self.assertEqual(sms.reference, ref, 'Sent SMS reference incorrect. Expected "{0}", got "{1}"'.format(ref, sms.reference))
            self.assertEqual(sms.status, gsmmodem.modem.SentSms.ENROUTE, 'Sent SMS status should have been {0} ("ENROUTE"), but is: {1}'.format(gsmmodem.modem.SentSms.ENROUTE, sms.status))
        self.modem.close()

    def test_sendSmsPduMode(self):
        """ Tests sending a SMS messages in PDU mode """
        self.initModem(None)
        self.modem.smsTextMode = False # Set modem to PDU mode
        self.modem._smsEncoding = "GSM"
        self.assertFalse(self.modem.smsTextMode)
        self.firstSMS = True
        for number, message, index, smsTime, smsc, pdu, sms_deliver_tpdu_length, ref, mem in self.tests:
            self.modem._smsRef = ref
            calcPdu = gsmmodem.pdu.encodeSmsSubmitPdu(number, message, ref)[0]
            pduHex = codecs.encode(compat.str(calcPdu.data), 'hex_codec').upper()
            if PYTHON_VERSION >= 3:
                pduHex = str(pduHex, 'ascii')

            def writeCallbackFunc(data):
                def writeCallbackFuncReadCSCS(data):
                    self.assertEqual('AT+CSCS=?\r', data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CSCS=?', data))
                    self.firstSMS = False

                def writeCallbackFunc2(data):
                    self.assertEqual('AT+CMGS={0}\r'.format(calcPdu.tpduLength), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGS={0}'.format(calcPdu.tpduLength), data))
                    self.modem.serial.writeCallbackFunc = writeCallbackFunc3
                    self.modem.serial.flushResponseSequence = False
                    self.modem.serial.responseSequence = ['> \r\n', '+CMGS: {0}\r\n'.format(ref), 'OK\r\n']

                def writeCallbackFunc3(data):
                    self.assertEqual('{0}{1}'.format(pduHex, chr(26)), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('{0}{1}'.format(pduHex, chr(26)), data))
                    self.modem.serial.flushResponseSequence = True

                if self.firstSMS:
                    return writeCallbackFuncReadCSCS(data)
                self.assertEqual('AT+CSCS="{0}"\r'.format(self.modem._smsEncoding), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CSCS="{0}"'.format(self.modem._smsEncoding), data))
                self.modem.serial.writeCallbackFunc = writeCallbackFunc2

            self.modem.serial.writeCallbackFunc = writeCallbackFunc
            sms = self.modem.sendSms(number, message)
            self.assertIsInstance(sms, gsmmodem.modem.SentSms)
            self.assertEqual(sms.number, number, 'Sent SMS has invalid number. Expected "{0}", got "{1}"'.format(number, sms.number))
            self.assertEqual(sms.text, message, 'Sent SMS has invalid text. Expected "{0}", got "{1}"'.format(message, sms.text))
            self.assertIsInstance(sms.reference, int, 'Sent SMS reference type incorrect. Expected "{0}", got "{1}"'.format(int, type(sms.reference)))
            self.assertEqual(sms.reference, ref, 'Sent SMS reference incorrect. Expected "{0}", got "{1}"'.format(ref, sms.reference))
            self.assertEqual(sms.status, gsmmodem.modem.SentSms.ENROUTE, 'Sent SMS status should have been {0} ("ENROUTE"), but is: {1}'.format(gsmmodem.modem.SentSms.ENROUTE, sms.status))
        self.modem.close()

    def test_sendSmsResponseMixedWithUnsolictedMessages(self):
        """ Tests sending a SMS messages (PDU mode), but with unsolicted messages mixed into the modem responses
        - the only difference here is that the modem's responseSequence contains unsolicted messages
        taken from github issue #11
        """
        self.initModem(None)
        self.modem.smsTextMode = False # Set modem to PDU mode
        self.modem._smsEncoding = "GSM"
        self.firstSMS = True
        for number, message, index, smsTime, smsc, pdu, sms_deliver_tpdu_length, ref, mem in self.tests:
            self.modem._smsRef = ref
            calcPdu = gsmmodem.pdu.encodeSmsSubmitPdu(number, message, ref)[0]
            pduHex = codecs.encode(compat.str(calcPdu.data), 'hex_codec').upper()
            if PYTHON_VERSION >= 3:
                pduHex = str(pduHex, 'ascii')

            def writeCallbackFunc(data):
                def writeCallbackFuncReadCSCS(data):
                    self.firstSMS = False
                    self.assertEqual('AT+CSCS=?\r', data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CSCS=?', data))

                def writeCallbackFunc2(data):
                    self.assertEqual('AT+CMGS={0}\r'.format(calcPdu.tpduLength), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGS={0}'.format(calcPdu.tpduLength), data))
                    self.modem.serial.writeCallbackFunc = writeCallbackFunc3
                    self.modem.serial.flushResponseSequence = True
                    # Note thee +ZDONR and +ZPASR unsolicted messages in the "response"
                    self.modem.serial.responseSequence = ['+ZDONR: "METEOR",272,3,"CS_ONLY","ROAM_OFF"\r\n', '+ZPASR: "UMTS"\r\n', '> \r\n']

                def writeCallbackFunc3(data):
                    self.assertEqual('{0}{1}'.format(pduHex, chr(26)), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('{0}{1}'.format(pduHex, chr(26)), data))
                    # Note thee +ZDONR and +ZPASR unsolicted messages in the "response"
                    self.modem.serial.responseSequence =  ['+ZDONR: "METEOR",272,3,"CS_ONLY","ROAM_OFF"\r\n', '+ZPASR: "UMTS"\r\n', '+ZDONR: "METEOR",272,3,"CS_PS","ROAM_OFF"\r\n', '+ZPASR: "UMTS"\r\n', '+CMGS: {0}\r\n'.format(ref), 'OK\r\n']

                if self.firstSMS:
                    return writeCallbackFuncReadCSCS(data)
                self.assertEqual('AT+CSCS="{0}"\r'.format(self.modem._smsEncoding), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CSCS="{0}"'.format(self.modem._smsEncoding), data))
                self.modem.serial.writeCallbackFunc = writeCallbackFunc2

            self.modem.serial.writeCallbackFunc = writeCallbackFunc
            sms = self.modem.sendSms(number, message)
            self.assertIsInstance(sms, gsmmodem.modem.SentSms)
            self.assertEqual(sms.number, number, 'Sent SMS has invalid number. Expected "{0}", got "{1}"'.format(number, sms.number))
            self.assertEqual(sms.text, message, 'Sent SMS has invalid text. Expected "{0}", got "{1}"'.format(message, sms.text))
            self.assertIsInstance(sms.reference, int, 'Sent SMS reference type incorrect. Expected "{0}", got "{1}"'.format(int, type(sms.reference)))
            self.assertEqual(sms.reference, ref, 'Sent SMS reference incorrect. Expected "{0}", got "{1}"'.format(ref, sms.reference))
        self.modem.close()

    def test_sendSms_refCount(self):
        """ Test the SMS reference counter operation when sending SMSs """
        self.initModem(None)

        ref = 0
        def writeCallbackFunc(data):
            if data.startswith('AT+CMGS'):
                self.modem.serial.flushResponseSequence = False
                self.modem.serial.responseSequence = ['> \r\n', '+CMGS: {0}\r\n'.format(ref), 'OK\r\n']
            else:
                self.modem.serial.flushResponseSequence = True
        self.modem.serial.writeCallbackFunc = writeCallbackFunc

        ref = 0
        sms = self.modem.sendSms("+27820000000", 'Test message')
        firstRef = sms.reference
        self.assertEqual(firstRef, 0)
        # Ensure the reference counter is incremented each time an SMS is sent
        ref = 1
        sms = self.modem.sendSms("+27820000000", 'Test message 2')
        reference = sms.reference
        self.assertEqual(sms.reference, firstRef + 1)
        # Ensure the reference counter rolls over once 255 is reached
        ref = 255
        self.modem._smsRef = 255
        sms = self.modem.sendSms("+27820000000", 'Test message 3')
        ref = 0
        self.assertEqual(sms.reference, 255)
        sms = self.modem.sendSms("+27820000000", 'Test message 4')
        self.assertEqual(sms.reference, 0)
        self.modem.close()

    def test_sendSms_waitForDeliveryReport(self):
        """ Test waiting for the status report when sending SMSs """
        self.initModem(None)
        causeTimeout = [False]
        def writeCallbackFunc(data):
            if data.startswith('AT+CMGS'):
                self.modem.serial.flushResponseSequence = False
                if causeTimeout[0]:
                    self.modem.serial.responseSequence = ['> \r\n', '+CMGS: 183\r\n', 'OK\r\n']
                else:
                    # Fake a delivery report notification after sending SMS
                    self.modem.serial.responseSequence = ['> \r\n', '+CMGS: 183\r\n', 'OK\r\n', 0.1, '+CDSI: "SM",3\r\n']
            elif data.startswith('AT+CMGR'):
                # Provide a fake status report - these are tested by the TestSmsStatusReports class
                self.modem.serial.responseSequence = ['+CMGR: 0,,24\r\n', '07917248014000F506B70AA18092020000317071518590803170715185418000\r\n', 'OK\r\n']
            else:
                self.modem.serial.flushResponseSequence = True
        self.modem.serial.writeCallbackFunc = writeCallbackFunc
        # Prepare send SMS response as well as "delivered" notification
        self.modem._smsRef = 183
        sms = self.modem.sendSms('0829200000', 'Test message', waitForDeliveryReport=True)
        self.assertIsInstance(sms, gsmmodem.modem.SentSms)
        self.assertNotEqual(sms.report, None, 'Sent SMS\'s "report" attribute should not be None')
        self.assertIsInstance(sms.report, gsmmodem.modem.StatusReport)
        self.assertEqual(sms.status, gsmmodem.modem.SentSms.DELIVERED, 'Sent SMS status should have been {0} ("DELIVERED"), but is: {1}'.format(gsmmodem.modem.SentSms.DELIVERED, sms.status))
        # Now test timeout event when waiting for delivery report
        causeTimeout[0] = True
        self.modem._smsRef = 183
        # Set deliveryTimeout to 0.05 - should timeout very quickly
        self.assertRaises(gsmmodem.exceptions.TimeoutException, self.modem.sendSms, **{'destination': '0829200000', 'text': 'Test message', 'waitForDeliveryReport': True, 'deliveryTimeout': 0.05})
        self.modem.close()

    def test_sendSms_reply(self):
        """ Test the reply() method of the ReceivedSms class """
        self.initModem(None)

        def writeCallbackFunc(data):
            if data.startswith('AT+CMGS'):
                self.modem.serial.flushResponseSequence = False
                self.modem.serial.responseSequence = ['> \r\n', '+CMGS: 0\r\n', 'OK\r\n']
            else:
                self.modem.serial.flushResponseSequence = True
        self.modem.serial.writeCallbackFunc = writeCallbackFunc

        receivedSms = gsmmodem.modem.ReceivedSms(self.modem, gsmmodem.modem.ReceivedSms.STATUS_RECEIVED_READ, '+27820000000', datetime(2013, 3, 8, 15, 2, 16, tzinfo=SimpleOffsetTzInfo(2)), 'Text message', '+9876543210')
        sms = receivedSms.reply('This is the reply')
        self.assertIsInstance(sms, gsmmodem.modem.SentSms)
        self.assertEqual(sms.number, receivedSms.number)
        self.assertEqual(sms.text, 'This is the reply')
        self.modem.close()

    def test_sendSms_noCgmsResponse(self):
        """ Test GsmModem.sendSms() but issue an invalid response from the modem """
        self.initModem(None)
        # Modem is just going to respond with "OK" to the send SMS command
        self.assertRaises(gsmmodem.exceptions.CommandError, self.modem.sendSms, '+27820000000', 'Test message')
        self.modem.close()

class TestStoredSms(unittest.TestCase):
    """ Tests processing/accessing SMS messages stored on the SIM card """

    def initModem(self, textMode, smsReceivedCallbackFunc):
        global FAKE_MODEM
        # Override the pyserial import
        mockSerial = MockSerialPackage()
        gsmmodem.serial_comms.serial = mockSerial
        self.modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --', smsReceivedCallbackFunc=smsReceivedCallbackFunc)
        self.modem.smsTextMode = textMode
        self.modem.connect()
        FAKE_MODEM = None

    def setUp(self):
        self.modem = None

    def tearDown(self):
        if self.modem != None:
            self.modem.close()

    def initFakeModemResponses(self, textMode):
        global FAKE_MODEM
        FAKE_MODEM = copy(fakemodems.GenericTestModem())
        modem = gsmmodem.modem.GsmModem('--weak ref object--')
        self.expectedMessages = [ReceivedSms(modem, Sms.STATUS_RECEIVED_UNREAD, '+27748577604', datetime(2013, 1, 28, 14, 51, 42, tzinfo=SimpleOffsetTzInfo(2)), 'Hello raspberry pi', None),
                                 ReceivedSms(modem, Sms.STATUS_RECEIVED_READ, '+2784000153099999', datetime(2013, 2, 7, 1, 31, 44, tzinfo=SimpleOffsetTzInfo(2)), 'New and here to stay! Don\'t just recharge SUPACHARGE and get your recharged airtime+FREE CellC to CellC mins & SMSs+Free data to use anytime. T&C apply. Cell C', None),
                                 ReceivedSms(modem, Sms.STATUS_RECEIVED_READ, '+27840001463', datetime(2013, 2, 7, 6, 24, 2, tzinfo=SimpleOffsetTzInfo(2)), 'Standard Bank: Your accounts are no longer FICA compliant. Please bring ID & proof of residence to any branch to reactivate your accounts. Queries? 0860003422.'),
                                 ReceivedSms(modem, Sms.STATUS_RECEIVED_READ, '5433', datetime(2015, 4, 1, 19, 37, 31, tzinfo=SimpleOffsetTzInfo(3)), 'Balans 15.00hrn, bonus 0.00hrn.\n***\nBezlimit na life:) 100 hv po 15 kop. 40.0 MB Internet po taryfu. 34 SMS po Ukraini. Paket poslug splacheno do 17.04.1')]
        if textMode:
            FAKE_MODEM.responses['AT+CMGL="REC UNREAD"\r'] = ['+CMGL: 0,"REC UNREAD","+27748577604",,"13/01/28,14:51:42+08"\r\n', 'Hello raspberry pi\r\n',
                                                              'OK\r\n']
            FAKE_MODEM.responses['AT+CMGL="REC READ"\r'] = ['+CMGL: 1,"REC READ","+2784000153099999",,"13/02/07,01:31:44+08"\r\n', 'New and here to stay! Don\'t just recharge SUPACHARGE and get your recharged airtime+FREE CellC to CellC mins & SMSs+Free data to use anytime. T&C apply. Cell C\r\n',
                                                            '+CMGL: 2,"REC READ","+27840001463",,"13/02/07,06:24:02+08"\r\n', 'Standard Bank: Your accounts are no longer FICA compliant. Please bring ID & proof of residence to any branch to reactivate your accounts. Queries? 0860003422.\r\n',
                                                            '+CMGL: 3,"REC READ","5433",,"15/04/01,19:37:31+12"\r\n', 'Balans 15.00hrn, bonus 0.00hrn.\n***\nBezlimit na life:) 100 hv po 15 kop. 40.0 MB Internet po taryfu. 34 SMS po Ukraini. Paket poslug splacheno do 17.04.1\r\n',
                                                            'OK\r\n']
            allMessages = FAKE_MODEM.responses['AT+CMGL="REC UNREAD"\r'][:-1]
            allMessages.extend(FAKE_MODEM.responses['AT+CMGL="REC READ"\r'])
            FAKE_MODEM.responses['AT+CMGL="ALL"\r'] = allMessages
            FAKE_MODEM.responses['AT+CMGL="STO UNSENT"\r'] = FAKE_MODEM.responses['AT+CMGL="STO SENT"\r'] = ['OK\r\n']
            FAKE_MODEM.responses['AT+CMGL=0\r'] = FAKE_MODEM.responses['AT+CMGL=1\r'] = FAKE_MODEM.responses['AT+CMGL=2\r'] = FAKE_MODEM.responses['AT+CMGL=3\r'] = FAKE_MODEM.responses['AT+CMGL=4\r'] = ['ERROR\r\n']
        else:
            FAKE_MODEM.responses['AT+CMGL=0\r'] = ['+CMGL: 0,0,,35\r\n', '07917248014000F3240B917247587706F400003110824115248012C8329BFD06C9C373B8B82C97E741F034\r\n',
                                                   'OK\r\n']
            FAKE_MODEM.responses['AT+CMGL=1\r'] = ['+CMGL: 1,1,,161\r\n', '07917248010080F020109172480010359099990000312070101344809FCEF21D14769341E8B2BC0CA2BF41737A381F0211DFEE131DA4AECFE92079798C0ECBCF65D0B40A0D0E9141E9B1080ABBC9A073990ECABFEB7290BC3C4687E5E73219144ECBE9E976796594168BA06199CD1E82E86FD0B0CC660F41EDB47B0E3281A6CDE97C659497CB2072981E06D1DFA0FABC0C0ABBF3F474BBEC02514D4350180E67E75DA06199CD060D01\r\n',
                                                   '+CMGL: 2,1,,159\r\n', '07917248010080F0240B917248001064F30000312070604220809F537AD84D0ECBC92061D8BDD681B2EFBA1C141E8FDF75377D0E0ACBCB20F71BC47EBBCF6539C8981C0641E3771BCE4E87DD741708CA2E87E76590589E769F414922C80482CBDF6F33E86D06C9CBF334B9EC1E9741F43728ECCE83C4F2B07B8C06D1DF2079393CA6A7ED617A19947FD7E5A0F078FCAEBBE97317285A2FCBD3E5F90F04C3D96030D88C2693B900\r\n',
                                                   '+CMGL: 3,1,,159\r\n', '07918340247399484007D035DA6C06000051401091731321A0050003720201846176D83D07C56A2E180C2D77B340E2B7BB3E07C15C30185AEE7629542A954258D6B3D3ED341DE40E83D86973599702C5603010DA0E82BF41B11A68FD86BB4034980B066A0A414937BD2C7797E920F81B440FCBF3E6BA0B34A381A6CD2908FE0655D7F270DA9D7681A0E175990E82BFE7ECFA193487B3C36374D9FD0691DFA0D8CD05A3B962\r\n',
                                                   'OK\r\n']
            allMessages = FAKE_MODEM.responses['AT+CMGL=0\r'][:-1]
            allMessages.extend(FAKE_MODEM.responses['AT+CMGL=1\r'])
            FAKE_MODEM.responses['AT+CMGL=4\r'] = allMessages
            FAKE_MODEM.responses['AT+CMGL=2\r'] = FAKE_MODEM.responses['AT+CMGL=3\r'] = ['OK\r\n']
            FAKE_MODEM.responses['AT+CMGL="REC UNREAD"\r'] = FAKE_MODEM.responses['AT+CMGL="REC READ"\r'] = FAKE_MODEM.responses['AT+CMGL="STO UNSENT"\r'] = FAKE_MODEM.responses['AT+CMGL="STO SENT"\r'] = FAKE_MODEM.responses['AT+CMGL="ALL"\r'] = ['ERROR\r\n']
            FAKE_MODEM.responses['AT+CMGR=0\r'] = ['+CMGR: 0,,35\r\n', '07917248014000F3240B917247587706F400003110824115248012C8329BFD06C9C373B8B82C97E741F034\r\n', 'OK\r\n']

    def test_listStoredSms_pdu(self):
        """ Tests listing/reading SMSs that are currently stored on the SIM card (PDU mode) """
        self.initFakeModemResponses(textMode=False)
        self.initModem(False, None)
        # Test getting all messages
        def writeCallbackFunc(data):
            self.assertEqual('AT+CMGL=4\r', data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGL=4', data))
        self.modem.serial.writeCallbackFunc = writeCallbackFunc
        messages = self.modem.listStoredSms()
        self.assertIsInstance(messages, list)
        self.assertEqual(len(messages), 4, 'Invalid number of messages returned; expected 3, got {0}'.format(len(messages)))

        for i in range(len(messages)):
            message = messages[i]
            expected = self.expectedMessages[i]
            self.assertIsInstance(message, expected.__class__)
            self.assertEqual(message.number, expected.number)
            self.assertEqual(message.status, expected.status)
            self.assertEqual(message.text, expected.text)
            self.assertEqual(message.time, expected.time)
        del messages

        # Test filtering
        tests = ((Sms.STATUS_RECEIVED_UNREAD, 1), (Sms.STATUS_RECEIVED_READ, 3), (Sms.STATUS_STORED_SENT, 0), (Sms.STATUS_STORED_UNSENT, 0))
        for status, numberOfMessages in tests:
            def writeCallbackFunc2(data):
                self.assertEqual('AT+CMGL={0}\r'.format(status), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGL={0}'.format(status), data))
            self.modem.serial.writeCallbackFunc = writeCallbackFunc2
            messages = self.modem.listStoredSms(status=status)
            self.assertIsInstance(messages, list)
            self.assertEqual(len(messages), numberOfMessages, 'Invalid number of messages returned for status: {0}; expected {1}, got {2}'.format(status, numberOfMessages, len(messages)))
            del messages

        # Test deleting messages after retrieval
        # Test deleting all messages
        expectedFilter = [4, ['1,4']]
        delCount = [0]
        def writeCallbackFunc3(data):
            self.assertEqual('AT+CMGL={0}\r'.format(expectedFilter[0]), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGL={0}'.format(expectedFilter[0]), data))
            def writeCallbackFunc4(data):
                self.assertEqual('AT+CMGD={0}\r'.format(expectedFilter[1][delCount[0]]), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGD={0}'.format(expectedFilter[1][delCount[0]]), data))
                delCount[0] += 1
            self.modem.serial.writeCallbackFunc = writeCallbackFunc4
        self.modem.serial.writeCallbackFunc = writeCallbackFunc3
        messages = self.modem.listStoredSms(status=Sms.STATUS_ALL, delete=True)
        self.assertIsInstance(messages, list)
        self.assertEqual(len(messages), 4, 'Invalid number of messages returned; expected 4, got {0}'.format(len(messages)))

        # Test deleting filtered messages
        expectedFilter[0] = 1
        expectedFilter[1] = ['1,0', '2,0', '3,0']
        delCount[0] = 0
        self.modem.serial.writeCallbackFunc = writeCallbackFunc3
        messages = self.modem.listStoredSms(status=Sms.STATUS_RECEIVED_READ, delete=True)

        # Test error handling if an invalid line is added between PDU data (line should be ignored)
        self.modem.serial.writeCallbackFunc = None
        self.modem.serial.modem.responses['AT+CMGL=4\r'].insert(1, 'AFSDLF SDKFJSKDLFJLKSDJF SJDLKFSKLDJFKSDFS\r\n')
        messages = self.modem.listStoredSms()
        self.assertIsInstance(messages, list)
        self.assertEqual(len(messages), 4, 'Invalid number of messages returned; expected 4, got {0}'.format(len(messages)))

    def test_listStoredSms_text(self):
        """ Tests listing/reading SMSs that are currently stored on the SIM card (text mode) """
        self.initFakeModemResponses(textMode=True)
        self.initModem(True, None)

        # Test getting all messages
        def writeCallbackFunc(data):
            self.assertEqual('AT+CMGL="ALL"\r', data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGL="ALL"', data))
        self.modem.serial.writeCallbackFunc = writeCallbackFunc
        messages = self.modem.listStoredSms()
        self.assertIsInstance(messages, list)
        self.assertEqual(len(messages), 4, 'Invalid number of messages returned; expected 4, got {0}'.format(len(messages)))

        for i in range(len(messages)):
            message = messages[i]
            expected = self.expectedMessages[i]
            self.assertIsInstance(message, expected.__class__)
            self.assertEqual(message.number, expected.number)
            self.assertEqual(message.status, expected.status)
            self.assertEqual(message.text, expected.text)
            self.assertEqual(message.time, expected.time)
        del messages

        # Test filtering
        tests = ((Sms.STATUS_RECEIVED_UNREAD, 'REC UNREAD', 1), (Sms.STATUS_RECEIVED_READ, 'REC READ', 3), (Sms.STATUS_STORED_SENT, 'STO SENT', 0), (Sms.STATUS_STORED_UNSENT, 'STO UNSENT', 0))
        for status, statusStr, numberOfMessages in tests:
            def writeCallbackFunc2(data):
                self.assertEqual('AT+CMGL="{0}"\r'.format(statusStr), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGL="{0}"'.format(statusStr), data))
            self.modem.serial.writeCallbackFunc = writeCallbackFunc2
            messages = self.modem.listStoredSms(status=status)
            self.assertIsInstance(messages, list)
            self.assertEqual(len(messages), numberOfMessages, 'Invalid number of messages returned for status: {0}; expected {1}, got {2}'.format(status, numberOfMessages, len(messages)))
            del messages

        # Test deleting messages after retrieval
        # Test deleting all messages
        expectedFilter = ['ALL', ['1,4']]
        delCount = [0]
        def writeCallbackFunc3(data):
            self.assertEqual('AT+CMGL="{0}"\r'.format(expectedFilter[0]), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGL="{0}"'.format(expectedFilter[0]), data))
            def writeCallbackFunc4(data):
                self.assertEqual('AT+CMGD={0}\r'.format(expectedFilter[1][delCount[0]]), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGD={0}'.format(expectedFilter[1][delCount[0]]), data))
                delCount[0] += 1
            self.modem.serial.writeCallbackFunc = writeCallbackFunc4
        self.modem.serial.writeCallbackFunc = writeCallbackFunc3
        messages = self.modem.listStoredSms(status=Sms.STATUS_ALL, delete=True)
        self.assertIsInstance(messages, list)
        self.assertEqual(len(messages), 4, 'Invalid number of messages returned; expected 4, got {0}'.format(len(messages)))

        # Test deleting filtered messages
        expectedFilter[0] = 'REC READ'
        expectedFilter[1] = ['1,0', '2,0', '3,0']
        delCount[0] = 0
        self.modem.serial.writeCallbackFunc = writeCallbackFunc3
        messages = self.modem.listStoredSms(status=Sms.STATUS_RECEIVED_READ, delete=True)

        # Test error handling when specifying an invalid SMS status value
        self.modem.serial.writeCallbackFunc = None
        self.assertRaises(ValueError, self.modem.listStoredSms, **{'status': 99})

    def test_processStoredSms(self):
        """ Tests processing and then "receiving" SMSs that are currently stored on the SIM card """
        self.initFakeModemResponses(textMode=False)

        expectedMessages = copy(self.expectedMessages)
        unread = expectedMessages.pop(0)
        expectedMessages.append(unread)

        i = [0]
        def smsCallbackFunc(sms):
            expected = expectedMessages[i[0]]
            self.assertIsInstance(sms, ReceivedSms)
            self.assertEqual(sms.number, expected.number)
            self.assertEqual(sms.status, expected.status)
            self.assertEqual(sms.text, expected.text)
            self.assertEqual(sms.time, expected.time)
            i[0] += 1

        self.initModem(False, smsCallbackFunc)

        commandsWritten = [False, False]
        def writeCallbackFunc(data):
            if data.startswith('AT+CMGL'):
                commandsWritten[0] = True
            elif data.startswith('AT+CMGD'):
                commandsWritten[1] = True
        self.modem.serial.writeCallbackFunc = writeCallbackFunc

        self.modem.processStoredSms()
        self.assertTrue(commandsWritten[0], 'AT+CMGL command not written to modem')
        self.assertTrue(commandsWritten[1], 'AT+CMGD command not written to modem')
        self.assertEqual(i[0], 4, 'Message received callback count incorrect; expected 4, got {0}'.format(i[0]))

        # Test unread only
        commandsWritten[0] = commandsWritten[1] = False
        i[0] = 0
        expectedMessages = [unread]
        self.modem.processStoredSms(unreadOnly=True)
        self.assertTrue(commandsWritten[0], 'AT+CMGL command not written to modem')
        self.assertTrue(commandsWritten[1], 'AT+CMGD command not written to modem')
        self.assertEqual(i[0], 1, 'Message received callback count incorrect; expected 1, got {0}'.format(i[0]))

    def test_deleteStoredSms(self):
        self.initFakeModemResponses(textMode=True)
        self.initModem(True, None)

        tests = (1,2,3)
        for index in tests:
            def writeCallbackFunc(data):
                self.assertEqual('AT+CMGD={0},0\r'.format(index), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGD={0},0'.format(index), data))
            self.modem.serial.writeCallbackFunc = writeCallbackFunc
            self.modem.deleteStoredSms(index)
        # Test switching SMS memory
        tests = ((5, 'TEST1'), (32, 'ME'))
        for index, mem in tests:
            def writeCallbackFunc(data):
                self.assertEqual('AT+CPMS="{0}"\r'.format(mem), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CPMS="{0}"'.format(mem), data))
                def writeCallbackFunc2(data):
                    self.assertEqual('AT+CMGD={0},0\r'.format(index), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGD={0},0'.format(index), data))
                self.modem.serial.writeCallbackFunc = writeCallbackFunc2
            self.modem.serial.writeCallbackFunc = writeCallbackFunc
            self.modem.deleteStoredSms(index, memory=mem)

    def test_deleteMultipleStoredSms(self):
        self.initFakeModemResponses(textMode=True)
        self.initModem(True, None)

        tests = (4,3,2,1)
        for delFlag in tests:
            # Test getting all messages
            def writeCallbackFunc(data):
                self.assertEqual('AT+CMGD=1,{0}\r'.format(delFlag), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGD=1,{0}'.format(delFlag), data))
            self.modem.serial.writeCallbackFunc = writeCallbackFunc
            self.modem.deleteMultipleStoredSms(delFlag)
        # Test switching SMS memory
        tests = ((4, 'TEST1'), (4, 'ME'))
        for delFlag, mem in tests:
            def writeCallbackFunc(data):
                self.assertEqual('AT+CPMS="{0}"\r'.format(mem), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CPMS="{0}"'.format(mem), data))
                def writeCallbackFunc2(data):
                    self.assertEqual('AT+CMGD=1,{0}\r'.format(delFlag), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGD=1,{0}'.format(delFlag), data))
                self.modem.serial.writeCallbackFunc = writeCallbackFunc2
            self.modem.serial.writeCallbackFunc = writeCallbackFunc
            self.modem.deleteMultipleStoredSms(delFlag, memory=mem)
        # Test default delFlag value
        delFlag = 4
        def writeCallbackFunc3(data):
            self.assertEqual('AT+CMGD=1,{0}\r'.format(delFlag), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGD=1,{0}'.format(delFlag), data))
        self.modem.serial.writeCallbackFunc = writeCallbackFunc3
        self.modem.deleteMultipleStoredSms()
        # Test invalid delFlag values
        tests = (0, 5, -3)
        for delFlag in tests:
            self.assertRaises(ValueError, self.modem.deleteMultipleStoredSms, **{'delFlag': delFlag})

    def test_readStoredSms_pdu(self):
        """ Tests reading stored SMS messages (PDU mode) """
        self.initFakeModemResponses(textMode=False)
        self.initModem(False, None)

        # Test basic reading
        index = 0
        def writeCallbackFunc(data):
            self.assertEqual('AT+CMGR={0}\r'.format(index), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGR={0}'.format(index), data))
        self.modem.serial.writeCallbackFunc = writeCallbackFunc
        message = self.modem.readStoredSms(index)
        expected = self.expectedMessages[index]
        self.assertIsInstance(message, expected.__class__)
        self.assertEqual(message.number, expected.number)
        self.assertEqual(message.status, expected.status)
        self.assertEqual(message.text, expected.text)
        self.assertEqual(message.time, expected.time)

        # Test switching SMS memory
        tests = ((0, 'TEST1'), (0, 'ME'))
        for index, mem in tests:
            def writeCallbackFunc(data):
                self.assertEqual('AT+CPMS="{0}"\r'.format(mem), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CPMS="{0}"'.format(mem), data))
                def writeCallbackFunc2(data):
                    self.assertEqual('AT+CMGR={0}\r'.format(index), data, 'Invalid data written to modem; expected "{0}", got: "{1}"'.format('AT+CMGR={0}'.format(index), data))
                self.modem.serial.writeCallbackFunc = writeCallbackFunc2
            self.modem.serial.writeCallbackFunc = writeCallbackFunc
            self.modem.readStoredSms(index, memory=mem)
            expected = self.expectedMessages[index]
            self.assertIsInstance(message, expected.__class__)
            self.assertEqual(message.number, expected.number)
            self.assertEqual(message.status, expected.status)
            self.assertEqual(message.text, expected.text)
            self.assertEqual(message.time, expected.time)


class TestSmsStatusReports(unittest.TestCase):
    """ Tests receiving SMS status reports """

    def initModem(self, smsStatusReportCallback):
        # Override the pyserial import
        self.mockSerial = MockSerialPackage()
        gsmmodem.serial_comms.serial = self.mockSerial
        self.modem = gsmmodem.modem.GsmModem('-- PORT IGNORED DURING TESTS --', smsStatusReportCallback=smsStatusReportCallback)
        self.modem.connect()

    def test_receiveSmsPduMode_zeroLengthSmscAndNonBCDTimeZoneValue(self):
        """ Test receiving PDU-mode SMS using data captured from failed operations/bug reports """
        tests = ((['+CMGR: 1,,26\r\n', '0006230E9126983575169498610103409544C26101034095448200\r\n', 'OK\r\n'],
                  Sms.STATUS_RECEIVED_READ, # message read status
                  '+62895357614989', # number
                  35, # reference
                  datetime(2016, 10, 30, 4, 59, 44, tzinfo=SimpleOffsetTzInfo(8)), # sentTime
                  datetime(2016, 10, 30, 4, 59, 44, tzinfo=SimpleOffsetTzInfo(7)), # deliverTime
                  StatusReport.DELIVERED), # delivery status
                 )

        callbackDone = [False]

        for modemResponse, msgStatus, number, reference, sentTime, deliverTime, deliveryStatus in tests:
            def smsCallbackFunc1(sms):
                try:
                    self.assertIsInstance(sms, gsmmodem.modem.StatusReport)
                    self.assertEqual(sms.status, msgStatus, 'Status report read status incorrect. Expected: "{0}", got: "{1}"'.format(msgStatus, sms.status))
                    self.assertEqual(sms.number, number, 'SMS sender number incorrect. Expected: "{0}", got: "{1}"'.format(number, sms.number))
                    self.assertEqual(sms.reference, reference, 'Status report SMS reference number incorrect. Expected: "{0}", got: "{1}"'.format(reference, sms.reference))
                    self.assertIsInstance(sms.timeSent, datetime, 'SMS sent time type invalid. Expected: datetime.datetime, got: {0}"'.format(type(sms.timeSent)))
                    self.assertEqual(sms.timeSent, sentTime, 'SMS sent time incorrect. Expected: "{0}", got: "{1}"'.format(sentTime, sms.timeSent))
                    self.assertIsInstance(sms.timeFinalized, datetime, 'SMS finalized time type invalid. Expected: datetime.datetime, got: {0}"'.format(type(sms.timeFinalized)))
                    self.assertEqual(sms.timeFinalized, deliverTime, 'SMS finalized time incorrect. Expected: "{0}", got: "{1}"'.format(deliverTime, sms.timeFinalized))
                    self.assertEqual(sms.deliveryStatus, deliveryStatus, 'SMS delivery status incorrect. Expected: "{0}", got: "{1}"'.format(deliveryStatus, sms.deliveryStatus))
                    self.assertEqual(sms.smsc, None, 'This SMS should not have any SMSC information')
                finally:
                    callbackDone[0] = True

            def writeCallback1(data):
                if data.startswith('AT+CMGR'):
                    self.modem.serial.flushResponseSequence = True
                    self.modem.serial.responseSequence = modemResponse

            self.initModem(smsStatusReportCallback=smsCallbackFunc1)
            # Fake a "new message" notification
            self.modem.serial.writeCallbackFunc = writeCallback1
            self.modem.serial.flushResponseSequence = True
            self.modem.serial.responseSequence = ['+CDSI: "SM",1\r\n']
            # Wait for the handler function to finish
            while callbackDone[0] == False:
                time.sleep(0.1)

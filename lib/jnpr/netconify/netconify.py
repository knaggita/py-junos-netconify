import pdb

import serial
import re
from time import sleep
from lxml import etree
from lxml.builder import E

_NETCONF_EOM = ']]>]]>'
_xmlns = re.compile('xmlns=[^>]+')
_xmlns_strip = lambda text: _xmlns.sub('',text)
_junosns = re.compile('junos:')
_junosns_strip = lambda text: _junosns.sub('',text)

__all__ = ['netconify']

##### =========================================================================
##### xmlmode_netconf
##### =========================================================================

class xmlmode_netconf(object):
  """
  provides access to the Junos XML API when bootstraping through the 
  serial console port
  """  
  def __init__(self, serial):
    """
    :serial: is an open serial.Serial object 
    """
    self._ser = serial
    self.hello = None

  def _receive(self):
    """ process the XML response into an XML object """
    rxbuf = []
    while True:
      line = self._ser.readline().strip()
      if not line: continue                       # if we got nothin, go again
      if _NETCONF_EOM == line: break              # check for end-of-message
      if not line.startswith('<'): continue       # skip any junk
      rxbuf.append(line)

    rxbuf[0] = _xmlns_strip(rxbuf[0])         # nuke the xmlns
    rxbuf[1] = _xmlns_strip(rxbuf[1])         # nuke the xmlns
    rxbuf = map(_junosns_strip, rxbuf)        # nuke junos: namespace
    return etree.XML(''.join(rxbuf))

  def open(self):
    """ start the XML API process and receive the 'hello' message """
    self._ser.write('xml-mode netconf need-trailer\n')
    self.hello = self._receive()

  def load(self, path, **kvargs):
    """
    load-override a Junos 'conf'-style file into the device.  if the
    load is successful, return :True:, otherwise return the XML reply
    structure for further processing

    :path:
      path to Junos conf-style text file on the local system.  this
      file could be a Jinja2 template file; and if so you should
      provide vars=<dict> on the call

    :kvargs['action']:
      determines the load mode.  this is 'override' by default.
      you could set this to merge or replace to perform those actions

    :kvargs['vars']:
      a <dict> of variables.  when this is given, the assumption is
      the conf file is a jinja2 template.  the variables will be 
      rendered into the template before loading into the device.
    """
    action = kvargs.get('action','override')
    conf_text = open(path,'r').read()    
    cmd = E('load-configuration', dict(format='text',action=action),
      E('configuration-text', conf_text )
    )
    rsp = self.rpc(etree.tostring(cmd))
    return rsp if rsp.findtext('.//ok') is None else True

  def commit_check(self):
    """ 
    performs the Junos 'commit check' operation.  if successful return
    :True: otherwise return the response as XML for further processing.
    """
    rsp = self.rpc('<commit-configuration><check/></commit-configuration>')
    return rsp if rsp.findtext('ok') is None else True

  def rollback(self):
    """ rollback that recent changes """
    cmd = E('load-configuration', dict(compare='rollback', rollback="0"))
    return self.rpc(etree.tostring(cmd))

  def rpc(self,cmd):
    """ 
    write the XML cmd and return the response

    :cmd: is a <str> of the XML command
    Return value is an XML object.  No error checking is performed.
    """

    if not cmd.startswith('<'): cmd = '<{}/>'.format(cmd)
    self._ser.write('<rpc>')
    self._ser.write(cmd)
    self._ser.write('</rpc>')
    return self._receive()

  def close(self):
    """ issue the XML API to close the session """
    self._ser.write('<close-session/>\n')

##### =========================================================================
##### netconify class
##### =========================================================================


class netconify(object):
  TIMEOUT = 0.2

  def __init__(self, port='/dev/ttyUSB0', **kvargs):
    self._ser = serial.Serial()    # this opens the port as well
    self._ser.port = port
    self.user = kvargs.get('user','root')
    self.passwd = kvargs.get('passwd','')
    self._ser.timeout = kvargs.get('timeout', self.TIMEOUT)
    self._ser.open()
    self.facts = {}
    self.nc = xmlmode_netconf( self._ser )

  def write(self, content):
    self._ser.write(content+'\n')
    self._ser.flush()
    return self._rd()

  def _rd(self):
    rxb = ''
    while True:
      sleep(self._ser.timeout)
      rxl = self._ser.readline()
      if not rxl: break
      rxb += rxl
    return rxb

  def sysctl(self,item):
    rd = self.write('sysctl {}'.format(item))
    return rd.split(': ')[1].split('\r')[0]

  def login(self, attempt = 0):
    self._ser.write('\n')
    rd = self._rd()

    # -------------------------------------------------------------------------
    # login:
    # -------------------------------------------------------------------------

    if not ('login' in rd):
      self.write('exit')
      if attempt < 3:
        self.login(attempt=attempt+1)
      else:
        raise RuntimeError("not at login prompt: ", rd)
    self.write(self.user)

    # -------------------------------------------------------------------------
    # at unix shell
    # -------------------------------------------------------------------------

    # @@@ need to handle the case when there is a password
    # self.facts['ostype'] = self.sysctl('kern.ostype')
    # self.facts['version'] = self.sysctl('kern.version')
    # self.facts['model'] = self.sysctl('hw.product.model').upper()

  def logout(self):
    self.write('exit')
    self._ser.close()


  
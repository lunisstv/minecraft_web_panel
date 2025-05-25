# mcrcon_patch.py
import signal as signal_module
import socket
from mcrcon import MCRcon, MCRconException
import logging

logger = logging.getLogger(__name__) # Verwende den Logger des Moduls

def apply_mcrcon_patch():
    logger.info("Applying MCRcon monkeypatch...")

    _original_MCRcon_init = MCRcon.__init__
    _original_MCRcon_connect = MCRcon.connect
    _original_MCRcon_command = MCRcon.command

    def _patched_mcrcon_init(self, host, password, port=25575, timeout=5, tlsmode=0, tls_certfile=None, tls_keyfile=None, tls_ca_certs=None, family=socket.AF_UNSPEC):
        self.host = host; self.password = password; self.port = port
        self.timeout = timeout if timeout and timeout > 0 else 5
        self.tlsmode = tlsmode; self.tls_certfile = tls_certfile; self.tls_keyfile = tls_keyfile
        self.tls_ca_certs = tls_ca_certs; self.family = family; self.socket = None
        logger.debug(f"Patched MCRcon.__init__ for {self.host}:{self.port}. Signal handler registration skipped.")

    def _patched_mcrcon_connect(self):
        if self.socket: return
        
        current_alarm_handler = signal_module.getsignal(signal_module.SIGALRM)
        current_alarm_time = signal_module.alarm(0) # Deaktiviere jeglichen bestehenden Alarm temporär

        # Setze einen Dummy-Handler, um Fehler zu vermeiden, falls das Original signal.signal aufruft
        # obwohl wir __init__ gepatcht haben, ist dies eine zusätzliche Sicherheitsmaßnahme.
        # Der Original-Handler wird nach dem connect-Versuch wiederhergestellt.
        try:
            signal_module.signal(signal_module.SIGALRM, lambda signum, frame: logger.debug("Dummy SIGALRM in connect"))
        except ValueError: # Kann passieren, wenn nicht im Main-Thread, aber __init__ sollte das schon verhindern
             logger.warning("Could not set dummy SIGALRM handler in connect (likely not main thread). Relying on patched __init__.")


        try:
            # Rufe die Original-Connect-Logik auf. Diese könnte signal.alarm() intern aufrufen,
            # aber da der SIGALRM-Handler durch unser gepatchtes __init__ nicht mehr der von mcrcon ist
            # (oder hier durch einen Dummy ersetzt wurde), sollte es nicht zum Timeout durch SIGALRM führen.
            _original_MCRcon_connect(self) # Aufruf der Originalmethode
            
            # Wichtig: Setze den Socket-Timeout *nachdem* der Socket im Original-Connect erstellt wurde.
            if self.socket:
                socket_timeout = self.timeout
                if socket_timeout is None or socket_timeout <= 0: socket_timeout = 5
                self.socket.settimeout(socket_timeout)
                logger.debug(f"Patched MCRcon.connect: Socket timeout set to {socket_timeout}s.")

        except Exception as e:
            # Hier sollten wir _original_MCRcon_disconnect(self) aufrufen, wenn es existiert
            # und self.socket nicht None ist, um Ressourcen freizugeben.
            if hasattr(self, 'socket') and self.socket:
                 try:
                     _original_MCRcon_disconnect(self)
                 except: pass # Ignoriere Fehler beim Disconnect im Fehlerfall
            raise # Lasse den ursprünglichen Fehler durch
        finally:
            # Stelle den ursprünglichen Alarm-Handler und die Zeit wieder her
            try:
                signal_module.signal(signal_module.SIGALRM, current_alarm_handler)
            except ValueError:
                logger.warning("Could not restore SIGALRM handler in connect (likely not main thread).")
            if current_alarm_time > 0 : # Nur wenn vorher ein Alarm gesetzt war
                 signal_module.alarm(current_alarm_time)


    def _patched_mcrcon_command(self, command_str):
        if not self.socket:
            _patched_mcrcon_connect(self) # Unser gepatchtes connect

        current_alarm_handler = signal_module.getsignal(signal_module.SIGALRM)
        current_alarm_time = signal_module.alarm(0)
        try:
            signal_module.signal(signal_module.SIGALRM, lambda signum, frame: logger.debug("Dummy SIGALRM in command"))
        except ValueError:
             logger.warning("Could not set dummy SIGALRM handler in command (likely not main thread).")

        try:
            # Rufe die Original-Command-Methode auf.
            # Ihre internen signal.alarm()-Aufrufe werden durch den Socket-Timeout obsolet.
            response = _original_MCRcon_command(self, command_str)
            return response
        except socket.timeout: # Fange den Socket-Timeout direkt
            raise MCRconException("RCON command timed out (socket timeout)")
        except Exception as e:
            raise
        finally:
            try:
                signal_module.signal(signal_module.SIGALRM, current_alarm_handler)
            except ValueError:
                 logger.warning("Could not restore SIGALRM handler in command (likely not main thread).")
            if current_alarm_time > 0:
                 signal_module.alarm(current_alarm_time)


    MCRcon.__init__ = _patched_mcrcon_init
    MCRcon.connect = _patched_mcrcon_connect
    MCRcon.command = _patched_mcrcon_command
    logger.info("MCRcon monkeypatch applied.")
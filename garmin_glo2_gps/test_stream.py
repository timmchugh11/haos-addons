import copy
import importlib.util
from pathlib import Path
import sys
sys.dont_write_bytecode=True
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('glo',Path(__file__).with_name('garmin_glo2.py'))
glo=importlib.util.module_from_spec(spec);sys.modules['glo']=glo;spec.loader.exec_module(glo)
RMC=b'$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n'

class StreamTests(unittest.TestCase):
    def run_stream(self,chunks,step=.1,readable=True):
        clock=[0.0];published=[];data=iter(chunks)
        class Sock:
            def recv(self,n): return next(data,b'')
        class Publisher:
            def publish(self,state): published.append((clock[0],copy.copy(state)))
        sock=Sock()
        def select(*args):
            clock[0]+=step
            return ([sock] if readable else [],[],[])
        with patch.object(glo.time_module,'monotonic',side_effect=lambda:clock[0]),patch.object(glo.select,'select',side_effect=select):
            with self.assertRaises(OSError) as error:
                glo.stream_session(sock,Publisher(),1,3,False)
        return published,str(error.exception)

    def test_high_rate_stream_is_throttled_without_disconnecting(self):
        fixes,error=self.run_stream([RMC]*100)
        self.assertEqual(error,'RFCOMM connection closed')
        self.assertGreaterEqual(len(fixes),9)
        self.assertLessEqual(len(fixes),10)
        self.assertTrue(all(b[0]-a[0]>=1 for a,b in zip(fixes,fixes[1:])))
        self.assertAlmostEqual(fixes[0][1].latitude,48.1173)
        self.assertEqual(fixes[0][1].course,84.4)

    def test_missing_data_times_out(self):
        fixes,error=self.run_stream([],step=.5,readable=False)
        self.assertFalse(fixes);self.assertEqual(error,'NMEA stream timed out')

    def test_unterminated_input_is_bounded(self):
        _,error=self.run_stream([b'x'*4096]*20)
        self.assertEqual(error,'NMEA input exceeded buffer limit')

    def test_gga_alone_does_not_republish_old_course(self):
        fixes,_=self.run_stream([b'$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47\r\n']*50)
        self.assertFalse(fixes)

if __name__=='__main__':unittest.main()

import os
import numpy as np
import soundfile as sf
from vispy import scene, color
from PyQt5 import QtGui, QtCore, QtWidgets
from scipy.signal import butter, sosfilt, sosfiltfilt, sosfreqz
from scipy import interpolate

#custom modules
from util import vispy_ext, fourier, spectrum, resampling, wow_detection, qt_theme, snd, widgets

def butter_bandpass(lowcut, highcut, fs, order=5):
	nyq = 0.5 * fs
	low = lowcut / nyq
	high = highcut / nyq
	sos = butter(order, [low, high], analog=False, btype='band', output='sos')
	return sos

def butter_bandpass_filter(data, lowcut, highcut, fs, order=5):
	sos = butter_bandpass(lowcut, highcut, fs, order=order)
	y = sosfiltfilt(sos, data)
	return y
	
class ResamplingThread(QtCore.QThread):
	notifyProgress = QtCore.pyqtSignal(int)
	def run(self):
		names, lag_curve, resampling_mode, sinc_quality, use_channels = self.settings
		resampling.run(names, lag_curve= lag_curve, resampling_mode = resampling_mode, sinc_quality=sinc_quality, use_channels=use_channels, prog_sig=self)
			
class ObjectWidget(QtWidgets.QWidget):
	"""
	Widget for editing OBJECT parameters
	"""
	# file_or_fft_settings_changed = QtCore.pyqtSignal(name='objectChanged')
	# settings_soft_changed = QtCore.pyqtSignal(name='objectChanged2')

	def __init__(self, parent=None):
		super(ObjectWidget, self).__init__(parent)
		
		self.parent = parent
		
		self.filename = ""
		self.deltraces = []
		
		
		self.display_widget = widgets.DisplayWidget(self.parent.canvas)
		self.resampling_widget = widgets.ResamplingWidget()
		self.audio_widget = snd.AudioWidget()
		self.inspector_widget = widgets.InspectorWidget()
		buttons = [self.display_widget, self.resampling_widget, self.audio_widget, self.inspector_widget ]

		vbox = QtWidgets.QVBoxLayout()
		for w in buttons: vbox.addWidget(w)
		vbox.addStretch(1.0)
		self.setLayout(vbox)

		self.resampling_thread = ResamplingThread()
		self.resampling_thread.notifyProgress.connect(self.resampling_widget.onProgress)

		
	def open_audio(self):
		#just a wrapper around load_audio so we can access that via drag & drop and button
		#pyqt5 returns a tuple
		filename = QtWidgets.QFileDialog.getOpenFileName(self, 'Open Audio', 'c:\\', "Audio files (*.flac *.wav)")[0]
		self.load_audio(filename)
			
	def load_audio(self, filename):

		# is the (dropped) file an audio file, ie. can it be read by pysoundfile?
		try:
			soundob = sf.SoundFile(filename)
			self.filename = filename
		except:
			print(filename+" could not be read, is it a valid audio file?")
			return
				
		#Cleanup of old data
		self.parent.canvas.init_fft_storages()
		self.delete_traces(not_only_selected=True)
		self.resampling_widget.refill(soundob.channels)
		
		#finally - proceed with spectrum stuff elsewhere
		self.parent.setWindowTitle('pytapesynch '+os.path.basename(self.filename))

		self.parent.canvas.set_file_or_fft_settings((self.filename, self.filename),
													 fft_size = self.display_widget.fft_size,
													 fft_overlap = self.display_widget.fft_overlap, )
													 # channels=(0, 1) )
											 
		data = resampling.read_lag(self.filename)
		for a0, a1, b0, b1, d in data:
			PanSample(self.parent.canvas, (a0, a1), (b0, b1), d)
		self.parent.canvas.pan_line.update()

	def save_traces(self):
		#get the data from the traces and regressions and save it
		resampling.write_lag(self.filename, [ (lag.a[0], lag.a[1], lag.b[0], lag.b[1], lag.pan) for lag in self.parent.canvas.pan_samples ] )
			
	def delete_traces(self, not_only_selected=False):
		self.deltraces= []
		for trace in reversed(self.parent.canvas.pan_samples):
			if (trace.selected and not not_only_selected) or not_only_selected:
				self.deltraces.append(trace)
		for trace in self.deltraces:
			trace.remove()
		self.parent.canvas.pan_line.update()
		#this means a file was loaded, so clear the undo stack
		if not_only_selected:
			self.deltraces= []
	
	def run_resample(self):
		if self.filename and self.parent.canvas.pan_samples:
			channels = self.resampling_widget.channels
			if channels and self.parent.canvas.pan_samples:
				lag_curve = self.parent.canvas.pan_line.data
				
				soundob = sf.SoundFile(self.filename)
				sr = soundob.samplerate
				signal = soundob.read(always_2d=True, dtype='float32')
				
				af = np.interp(np.arange(len(signal[:,0])), lag_curve[:,0]*sr, lag_curve[:,1])
				
				sf.write(self.filename[:-4]+'test.wav', signal[:,1]*af, sr, subtype='FLOAT')
				# self.resampling_thread.settings = ((self.filename,), lag_curve, self.resampling_widget.mode, self.resampling_widget.sinc_quality, channels)
				# self.resampling_thread.start()
		
	def run_resample_batch(self):
		if self.filename and self.parent.canvas.pan_samples:
			filenames = QtWidgets.QFileDialog.getOpenFileNames(self, 'Open Files for Batch Resampling', 'c:\\', "Audio files (*.flac *.wav)")[0]
			channels = self.resampling_widget.channels
			if channels and self.parent.canvas.pan_samples:
				lag_curve = self.parent.canvas.pan_line.data
				self.resampling_thread.settings = (filenames, lag_curve, self.resampling_widget.mode, self.resampling_widget.sinc_quality, channels)
				self.resampling_thread.start()
					
class MainWindow(widgets.MainWindow):

	def __init__(self):
		widgets.MainWindow.__init__(self, "pytapesynch", ObjectWidget, Canvas)
		mainMenu = self.menuBar() 
		fileMenu = mainMenu.addMenu('File')
		editMenu = mainMenu.addMenu('Edit')
		button_data = ( (fileMenu, "Open", self.props.open_audio, "CTRL+O"), \
						(fileMenu, "Save", self.props.save_traces, "CTRL+S"), \
						(fileMenu, "Resample", self.props.run_resample, "CTRL+R"), \
						(fileMenu, "Batch Resample", self.props.run_resample_batch, "CTRL+B"), \
						(fileMenu, "Exit", self.close, ""), \
						(editMenu, "Delete Selected", self.props.delete_traces, "DEL"), \
						)
		self.add_to_menu(button_data)

class PanLine:
	"""Stores and displays the average, ie. master speed curve."""
	def __init__(self, vispy_canvas):
		
		self.vispy_canvas = vispy_canvas
		
		#create the speed curve visualization
		self.data = np.zeros((2, 2), dtype=np.float32)
		self.data[:, 0] = (0, 999)
		self.data[:, 1] = (0, 0)
		self.line_speed = scene.Line(pos=self.data, color=(0, 0, 1, .5), method='gl')
		self.line_speed.parent = vispy_canvas.speed_view.scene
		
	def update(self):

		#set the output data

		if self.vispy_canvas.pan_samples:
			#create the array for sampling
			self.vispy_canvas.pan_samples.sort(key=lambda tup: tup.t)
			num = self.vispy_canvas.num_ffts
			
			#get the times at which the average should be sampled
			times = np.linspace(0, num * self.vispy_canvas.hop / self.vispy_canvas.sr, num=num)
			# out = np.zeros((len(times), len(self.vispy_canvas.pan_samples)), dtype=np.float32)
			# #lerp and sample all lines, use NAN for missing parts
			# for i, line in enumerate(self.vispy_canvas.pan_samples):
				# line_sampled = np.interp(times, line.times, line.pan, left = np.nan, right = np.nan)
				# out[:, i] = line_sampled
			# #take the mean and ignore nans
			# mean_with_nans = np.nanmean(out, axis=1)
			# #lerp over nan areas
			# nans, x = wow_detection.nan_helper(mean_with_nans)
			# mean_with_nans[nans]= np.interp(x(nans), x(~nans), mean_with_nans[~nans])
			# self.data[:, 1] = mean_with_nans
			
			sample_times = [sample.t for sample in self.vispy_canvas.pan_samples]
			sample_pans = [sample.pan for sample in self.vispy_canvas.pan_samples]
			pan = np.interp(times, sample_times, sample_pans)
			#create the speed curve visualization, boost it a bit to distinguish from the raw curves
			self.data = np.zeros((len(times), 2), dtype=np.float32)
			self.data[:, 0] = times
			self.data[:, 1] = pan
			self.line_speed.set_data(pos=self.data)	
				
class PanSample():
	"""Stores a single sinc regression's data and displays it"""
	def __init__(self, vispy_canvas, a, b, pan):
		
		self.a = a
		self.b = b
		
		self.t = (a[0]+b[0])/2
		self.width= abs(a[0]-b[0])
		self.f = (a[1]+b[1])/2
		self.height= abs(a[1]-b[1])
		self.spec_center = (self.t, self.f)
		self.speed_center = (self.t, pan)
		# self.times = times
		self.pan = pan
		self.rect = scene.Rectangle(center=(self.t, self.f), width=self.width, height=self.height, radius=0, parent=vispy_canvas.spec_view.scene)
		self.rect.color = (1, 1, 1, .5)
		self.rect.transform = vispy_canvas.spectra[-1].mel_transform
		self.rect.set_gl_state('additive')
		self.selected = False
		self.vispy_canvas = vispy_canvas
		self.initialize()
		
	def initialize(self):
		"""Called when first created, or revived via undo."""
		self.vispy_canvas.pan_samples.append(self)
		self.vispy_canvas.pan_line.update()

	def deselect(self):
		"""Deselect this line, ie. restore its colors to their original state"""
		self.selected = False
		self.rect.color = (1, 1, 1, .5)
		
	def select(self):
		"""Toggle this line's selection state"""
		self.selected = True
		self.rect.color = (0, 0, 1, .5)
		
	def toggle(self):
		"""Toggle this line's selection state"""
		if self.selected:
			self.deselect()
		else:
			self.select()
			
	def select_handle(self, multi=False):
		if not multi:
			for lag_sample in self.vispy_canvas.pan_samples:
				lag_sample.deselect()
		self.toggle()
	
	def show(self):
		self.rect.parent = self.vispy_canvas.spec_view.scene
		
	def hide(self):
		self.rect.parent = None
		self.deselect()
		
	def remove(self):
		self.hide()
		#note: this has to search the list
		self.vispy_canvas.pan_samples.remove(self)
		
class Canvas(spectrum.SpectrumCanvas):

	def __init__(self):
		spectrum.SpectrumCanvas.__init__(self, bgcolor="black")
		self.unfreeze()
		self.pan_samples = []
		self.pan_line = PanLine(self)
		self.freeze()
		
	#called if either  the file or FFT settings have changed
	def set_file_or_fft_settings(self, files, fft_size = 256, fft_overlap = 1, channels=(0,1)):
		if files:
			self.compute_spectra(files, fft_size, fft_overlap, channels)
			self.pan_line.update()
		
	def on_mouse_press(self, event):
		#selection
		b = self.click_spec_conversion(event.pos)
		#are they in spec_view?
		if b is not None:
			self.props.audio_widget.cursor(b[0])
		if event.button == 2:
			closest_lag_sample = self.get_closest( self.pan_samples, event.pos )
			if closest_lag_sample:
				closest_lag_sample.select_handle()
				event.handled = True
	
	def on_mouse_release(self, event):
		#coords of the click on the vispy canvas
		if self.props.filename and (event.trail() is not None) and event.button == 1:
			last_click = event.trail()[0]
			click = event.pos
			if last_click is not None:
				a = self.click_spec_conversion(last_click)
				b = self.click_spec_conversion(click)
				#are they in spec_view?
				if a is not None and b is not None:
					if "Shift" in event.modifiers:
						
						
						soundob = sf.SoundFile(self.props.filename)
						fft_size = 4096
						hop = fft_size//4
						sr = soundob.samplerate
						signal = soundob.read(always_2d=True, dtype='float32')
						#now store this for retrieval later
						L = fourier.stft(signal[:,0], fft_size, hop, "hann", 1)
						R = fourier.stft(signal[:,1], fft_size, hop, "hann", 1)
						L = 20 * np.log10(L)
						R = 20 * np.log10(R)
						
						times = sorted((a[0], b[0]))
						t0 = times[0]
						t1 = times[1]
						freqs = sorted((a[1], b[1]))
						fL = max(freqs[0], 1)
						fU = min(freqs[1], sr//2-1)
						first_fft_i = 0
						num_bins, last_fft_i = L.shape
						#we have specified start and stop times, which is the usual case
						if t0:
							#make sure we force start and stop at the ends!
							first_fft_i = max(first_fft_i, int(t0*sr/hop)) 
						if t1:
							last_fft_i = min(last_fft_i, int(t1*sr/hop))

						#bin indices of the starting band
						N = fft_size
						
						def freq2bin(f): return max(1, min(num_bins-3, int(round(f * N / sr))) )
						bL = freq2bin(fL)
						bU = freq2bin(fU)
						
						dBs = np.nanmean(L[bL:bU,first_fft_i:last_fft_i]-R[bL:bU,first_fft_i:last_fft_i], axis=0)
						fac = np.power(10, dBs/20)
						
						# out_times = np.arange(first_fft_i, last_fft_i)*hop/sr
						PanSample(self, a, b, np.mean(fac) )
			
# -----------------------------------------------------------------------------
if __name__ == '__main__':
	appQt = QtWidgets.QApplication([])
	
	#style
	appQt.setStyle(QtWidgets.QStyleFactory.create('Fusion'))
	appQt.setPalette(qt_theme.dark_palette)
	appQt.setStyleSheet("QToolTip { color: #ffffff; background-color: #353535; border: 1px solid white; }")
	
	win = MainWindow()
	win.show()
	appQt.exec_()
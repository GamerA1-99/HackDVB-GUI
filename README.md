# **HackDVB GUI**

A user-friendly graphical interface for creating and broadcasting DVB-S/S2 transport streams using FFmpeg, TSDuck, and DekTec hardware.

HackDVB GUI is the spiritual digital successor to the analogue HackTV project. It provides a comprehensive suite of tools to encode media files, multiplex them into multiple services (channels), generate the necessary DVB tables (including a full EPG), and broadcast the resulting stream with a DekTec modulator card.


### **Latest version can be downloaded here:** [HackDVB GUI - Beta 1.00](https://github.com/GamerA1-99/HackDVB-GUI/releases/tag/Beta-1-0-0)


## **Features**
HackDVB GUI is designed to simplify the complex process of DVB broadcasting by providing a powerful, all-in-one interface.

* **Multi-Service Multiplexing:** Create multiple TV and Radio channels within a single broadcast stream.

* **Hardware-Accelerated Encoding:** Offload CPU-intensive tasks to your GPU with support for NVIDIA CUDA (NVENC) and Intel Quick Sync Video (QSV).

* **Advanced Encoding Options:** Full control over video/audio codecs (MPEG-2, H.264, MP2, AC3, AAC), bitrates, presets, resolutions, framerates, and more.

* **DVB-S & DVB-S2 Support:** Configure all necessary transmission parameters, including modulation, FEC, symbol rate, and frequency, with an automatic Mux Rate calculator.

* Also no DVB-T, T2, C or C2 support just DVB-S and S2. Reason is that my Dektec card (the DTA-107) used for developing this program just has support for DVB-S and S2 standards so can’t really test if I implement DVB-T or DVB-C support that it will work properly with everything and all the functions. But until then I have made it so it’s possible to extract the generated commands in the program to a txt file or a bat file (can also just copy paste it) so in theory if someone wants to use other dvb standards with their supported Dektec cards, they can extract a finished generated commands and replace the DVB-S bits of the command to other DVB standards and should work then as long it’s follows tsduck parameter for that standard and requires all the dependencies are available/added into the system PATH. But as fast I get my hand on other cards with support for other DVB standards I will of corse add support for the remaining DVB standards. But better to leave it out then blindly code it in and hope that it is working for now.

* **Comprehensive Input Support:** Use single media files, FFmpeg concat playlists, user-friendly UI managed playlists, or live UDP/IP streams as sources.

* **Full EPG Management:**
A powerful EPG Editor to create, edit, and manage your broadcast schedule.
Auto-generate EPG from media file durations, complete with metadata options.
Automatic gap-filling to ensure a valid and displayable EPG on receivers.

* **Subtitle Flexibility:**
Burn-in: Permanently render external .srt, .vtt or .ass subtitles onto the video.

* **DVB and Teletext subtitles:** Pass through embedded subtitle tracks from the source file for viewer-toggleable subtitles.

* **Audio Control:** Select multiple audio tracks from your source files for multi-language broadcasts and apply EBU R128 loudness normalization for consistent volume. Viewer-toggleable audio is available when more then one audio track is being broadcasted. 

* **Standalone Media Tools:** A dedicated "Tools" tab for batch processing files:

* **Video Converter:** Re-encode files to standard formats.

* **Remux to TS:** Quickly repackage .mp4 or .mkv files into a .ts container without re-encoding.

* **Bitrate Converter:** Re-encode files to a different bitrate.

* **Subtitle Ripper:** Extract embedded subtitles into .srt or .ass files.

* **Live Previews:** See the generated ffmpeg and tsp commands update in real-time as you change settings.

* **Detailed Logging:** View live log output from all backend processes to monitor performance and troubleshoot errors.

* **Save & Load Configurations:** Save your entire session—all channels, inputs, and settings—to a single JSON file and load it back later.

* **Built-in Documentation:** An in-app wiki provides detailed explanations of every feature and the underlying technologies.

## **How It Works**
HackDVB GUI acts as an orchestrator for several powerful command-line tools, piping the output of one to the input of the next:

* **FFmpeg:** Handles all media decoding, filtering (subtitles, loudnorm), and re-encoding. It creates a compliant MPEG Transport Stream (MPEG-TS) containing all the video and audio for your services.

* **TDT Injector (tdt.exe):** A small companion utility that generates TDT/TOT packets, which are essential for a receiver's clock to synchronize and display EPG data correctly.

* **TSDuck (tsp):** Receives the stream from FFmpeg and performs the final muxing. It injects critical DVB Service Information (SI) tables (like NIT, SDT), injects the EPG data (EIT) from the generated XML file, and merges the time packets from the TDT Injector.

* **DekTec Hardware:** TSDuck outputs the final, constant-bitrate transport stream to the DekTec modulator card, which converts the digital stream into a real RF signal for broadcast.

## **Requirements**

**Hardware**

* A **DekTec DVB-S/S2 Modulator Card (e.g., DTA-107, DTA-2111) with an available PCI or PCIe slot.**

* **CPU:** A modern multi-core CPU (Intel Core i5/i7, AMD Ryzen 5 or better) is recommended, especially for multi-channel or HD encoding.

* **GPU (Optional but Recommended):** An NVIDIA GPU (GTX 1050 or newer) or an Intel CPU with an integrated GPU is highly recommended for hardware-accelerated encoding.

* **RAM:** 8 GB minimum, 16 GB+ recommended.

* **Storage:** a SSD for the OS is highly recomended as it will improve the speed and make the pc run smoother when running this program and generally when using. Also a SSD or HDD for storage of your mediafiles etc is also recomended (if not using just livestreams like IP/UDP). 

### **Lower specs may work other then the recomended ones, but can't promise everything will work as intended.**

**Software**

* **OS: Windows 10 or 11 (Just 64-Bit support) (Linux support coming in the future)**

* **Python 3.x (64-Bit, "standalone installer", and not "install manager") [Download here](https://www.python.org/downloads/) (Remember when installing, press on customize tab and also tick of all the checkmarks like on the first screen: "Use admin privilges when installing py.exe" and "Add python.exe to PATH". Also tick on all optional options for best support and minimizing error or missing python dependencies in the customize installation tab/section.)**

* **DekTec Drivers: Must be installed and check that the card appears correctly in Device Management** [Download here](https://www.dektec.com/downloads/SDK/)

* **FFmpeg: Must be installed and available in your system's PATH.** [Download here](https://www.ffmpeg.org/)

* **TSDuck: Must be installed and available in your system's PATH.** [Download here](https://tsduck.io/)

* **TDT Injector (tdt.exe): This utility should be included with the application. If not working or complaning about its missing then it must be installed and available in your system's PATH.** [Download here](https://github.com/GamerA1-99/HackDVB-TDT.exe)

* **PyInstaller 6.x (64-bit) [Download here](https://pyinstaller.org/en/stable/) (Optional, just for creating/compile your own .exe file and not needed for the already created .exe to work or .py under download tab)**

* **The application includes a dependency checker and info tab that will guide you if any of these required dependencies are missing.**

# **Usage**

### **After all the dependencies are installed just download the .rar file containing the "HackDVB GUI.exe" file and open it**


* **Services Tab:** Click "Add Channel" to create a new service. Give it a name, provider, and a unique Program Number (SID).

* **Inputs Tab:** For each service, select an input type (e.g., Playlist) and add your media files. Use the "Probe Input Tracks" button to detect and select specific audio or embedded subtitle tracks.

* **EPG (Optional):** Use the "Auto-generate EPG" button for a quick schedule, or open the "Create/Edit EPG" editor for full control.

* **Encoding & Muxing Tab:** Configure your global video and audio settings. Enable CUDA or QSV if you have compatible hardware.

* **DVB Broadcast Tab:** Enter the parameters for your satellite transponder (Frequency, Symbol Rate, etc.) and click "Auto-Calculate" for the Mux Rate.

* **Start Broadcast:** Click the "Start Broadcast" button to begin transmission! Monitor the "Live Log" for status and errors.

**A Note on Encryption**
This application is designed for educational and experimental broadcasting of unencrypted, free-to-air content only. It does not support or include any features for scrambling the broadcast stream with a Conditional Access (CA) system.

## **License**
This project is licensed under the MIT License. See the LICENSE file for details.

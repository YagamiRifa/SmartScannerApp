import tkinter as tk
from tkinter import ttk
import cv2
from PIL import Image, ImageTk
from picamera2 import Picamera2
import requests
import time
import os  
import RPi.GPIO as GPIO  
import threading
import queue
from datetime import datetime
from calendar import monthrange
from exp_scanner.date_parser import date_standard

# ==================== [ KONFIGURASI ] ====================
BASE_SERVER_URL = "http://192.168.137.1:8000" #TUFDASH15RIFA
LARAVEL_API_URL = f"{BASE_SERVER_URL}/api/scanner/batch"
LARAVEL_CHECK_URL = f"{BASE_SERVER_URL}/api/scanner/check"

class SmartScannerApp:
    # ==================== [ INISIALISASI ] ===================   
    def __init__(self, window):
        self.waktu_mulai_aplikasi = time.time()

        self.window = window
        self.window.title("Smart Scanner App")
        self.window.geometry("800x480")
        self.window.resizable(False, False)
        self.window.attributes('-fullscreen', True)
        self.window.configure(bg="black")

        subfolder_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        self.output_folder = os.path.join("captures", subfolder_name)
        self.failed_folder = os.path.join("failed_captures")
        os.makedirs(self.output_folder, exist_ok=True)
        os.makedirs(self.failed_folder, exist_ok=True)

        # Pengaturan Resolusi (Dinamis untuk masa depan)
        self.camera_resolution = (1080, 1920)
        self.is_changing_camera = False 

        self.PINS = {
            "RST": 0,  
            "SET": 5,  
            "MID": 6,  
            "RHT": 16, 
            "DWN": 26, 
            "LET": 20, 
            "UP" : 21  
        }
        self.init_gpio()

        self.manual_date_chars = list(datetime.now().strftime("%d%m%Y"))
        self.current_digit_index = 0
        self.prev_frame_time = 0
        self.new_frame_time = 0
        self.last_failed_save_time = 0
        self.start_scan_time = 0

        self.status_koneksi_terakhir = False
        self.status_koneksi_teks = "Checking..."
        self.status_koneksi_warna = (15, 196, 241)
        
        # Alur Wajib Barcode
        self.current_step = "IDLE_BARCODE" 
        self.scanned_barcode = "-"
        self.scanned_date = "-"
        self.nama_barang_terbaca = ""
        
        # self.notif_pesan_teks = "Memeriksa jaringan ke server..."
        # self.notif_pesan_warna = (15, 196, 241)
        # self.is_first_network_check = True

        # --- MODIFIKASI 1: Status AI Loading ---
        self.is_ai_ready = False 
        self.notif_pesan_teks = "Memuat Sistem AI...\nMohon tunggu sebentar."
        self.notif_pesan_warna = (230, 126, 34) # Warna Orange
        self.is_first_network_check = True

        self.btn_confirm_send = None
        self.btn_retry_date = None
        self.btn_cancel_barcode = None
        self.btn_manual_input = None
        self.btn_toggle_scan = None
        
        self.current_display_frame = None
        self.last_highres_frame = None 

        self.task_queue = queue.Queue()
        self.is_processing_ai = False
        self.ai_thread = threading.Thread(target=self.ai_worker_loop, daemon=True)
        self.ai_thread.start()
        
        print("Menginisialisasi Kamera dan AI di latar belakang...\nMohon tunggu.\n")
        self.model = None
        
        # Inisialisasi Kamera Resolusi Awal
        self.picam = Picamera2()
        config = self.picam.create_preview_configuration(main={"size": self.camera_resolution})
        self.picam.configure(config)
        self.picam.start()
        self.picam.set_controls({"AfMode": 2}) 

        self.video_label = tk.Label(window, bg="black", bd=0, highlightthickness=0)
        self.video_label.place(x=0, y=0, width=800, height=480)

        # Tombol Antarmuka Sisi Kanan
        self.btn_exit = tk.Button(self.video_label, text="❌ KELUAR", font=("Arial", 9, "bold"), bg="#34495e", fg="#bdc3c7", command=self.close_application, bd=0, activebackground="#2c3e50", activeforeground="white")
        self.btn_exit.place(x=680, y=425, width=100, height=35)
        
        self.btn_screenshot = tk.Button(self.video_label, text="SCREENSHOT", font=("Arial", 8, "bold"), bg="#8e44ad", fg="white", command=self.take_screenshot, bd=0, activebackground="#9b59b6", activeforeground="white")
        self.btn_screenshot.place(x=680, y=380, width=100, height=35)

        self.btn_capture = tk.Button(self.video_label, text="📷 CAPTURE", font=("Arial", 8, "bold"), bg="#27ae60", fg="white", command=self.take_capture_highres, bd=0, activebackground="#2ecc71", activeforeground="white")
        self.btn_capture.place(x=680, y=335, width=100, height=35)

        # Tampilkan tombol aksi di awal (IDLE_BARCODE)
        self.tampilkan_tombol_scan_ulang_saja()

        self.window.protocol("WM_DELETE_WINDOW", self.close_application)
        self.update_pipeline()
        self.baca_tombol_gpio_loop()
        self.window.after(500, self.cek_koneksi_berkala)

        self.window.after(0, self.cetak_waktu_gui)

    # ==================== [ PENCATAT WAKTU GUI ] ===================
    def cetak_waktu_gui(self):
        waktu_gui_muncul = time.time()
        durasi_gui = waktu_gui_muncul - self.waktu_mulai_aplikasi
        print(f"\n✅ Durasi GUI: {durasi_gui:.2f} detik")

    # ============== [ FUNGSI TAMBAHAN: GUIDANCE ] ==============
    def get_guidance_text(self):
        """Mengembalikan teks panduan kontrol berdasarkan state aplikasi."""
        if self.current_step == "IDLE_BARCODE":
            return "MID: Scan Barcode | RST: Keluar (Tahan 3s)"
        elif self.current_step == "BARCODE":
            return "MID: Pause Scan | RST: Keluar (Tahan 3s)"
        elif self.current_step == "IDLE_TANGGAL":
            return "MID: Scan Tanggal | SET: Input Manual | RST: Reset"
        elif self.current_step == "TANGGAL":
            return "MID: Pause Scan | RST: Keluar (Tahan 3s)"
        elif self.current_step == "KONFIRMASI":
            return "MID: Kirim | L: Scan Tanggal Ulang | RST: Reset"
        elif self.current_step == "MANUAL_INPUT":
            return "MID: Simpan | UP/DWN: Ubah Angka | L/R: Kursor | RST: Batal"
        return ""

    # ============== [ LOGIKA PERUBAHAN RESOLUSI DINAMIS ] ==============
    def set_camera_resolution(self, width, height):
        """Ubah ukuran resolusi kamera secara programatik."""
        def _apply_res():
            self.is_changing_camera = True
            try:
                self.camera_resolution = (width, height)
                self.picam.stop()
                config = self.picam.create_preview_configuration(main={"size": self.camera_resolution})
                self.picam.configure(config)
                self.picam.start()
                self.picam.set_controls({"AfMode": 2})
            finally:
                self.is_changing_camera = False

        threading.Thread(target=_apply_res, daemon=True).start()

    # --- MODIFIKASI 3: Callback saat AI siap ---
    def gui_update_ai_ready(self, durasi):
        self.is_ai_ready = True
        self.notif_pesan_teks = f"AI Siap! ({durasi:.1f} detik)\nTekan 'MID' untuk Mulai."
        self.notif_pesan_warna = (46, 204, 113) # Warna Hijau

    # ============== [ PEMROSESAN KECERDASAN BUATAN ASINKRON ] =========
    def ai_worker_loop(self):
        # 1. LAZY LOADING DIMULAI DI SINI
        from ultralytics import YOLO
        import pytesseract
        from pyzbar.pyzbar import decode
        
        # 2. MUAT MODEL SETELAH GUI MUNCUL
        if self.model is None:
            self.model = YOLO("best_ncnn_model", task="detect")

            waktu_selesai_inisiasi = time.time()
            durasi_total = waktu_selesai_inisiasi - self.waktu_mulai_aplikasi
            print(f"Model YOLO siap digunakan!\n✅ Durasi Inisiasi: {durasi_total:.2f} detik")
            
            # --- MODIFIKASI 4: Panggil GUI dari Thread Belakang ---
            # Menggunakan lambda agar kita bisa mengirimkan data durasi_total ke GUI
            self.window.after(0, lambda: self.gui_update_ai_ready(durasi_total))


        while True:
            task = self.task_queue.get()
            
            waktu_mulai_ai = time.time()
            waktu_antri = task.get('enqueue_time', waktu_mulai_ai)

            task_type = task['task_type']
            frame = task['frame']
            w, target_h = task['dimensions']
            
            # --- PERHITUNGAN SKALA DINAMIS ---
            skala = w / 800.0
            fs_standar = 0.5 * skala   
            fs_kecil = 0.45 * skala    
            
            thick_tipis = max(1, int(1 * skala))
            thick_sedang = max(1, int(2 * skala))
            thick_tebal = max(2, int(4 * skala))
            
            pad_y_box = int(10 * skala)
            min_y_batas = int(15 * skala)
            pad_x_kanan = int(120 * skala)
            pad_y_fps = int(30 * skala)

            if task_type == 'BARCODE':
                detected_barcodes = decode(frame)
                barcode_success = False
                
                for barcode in detected_barcodes:
                    scanned_barcode_raw = barcode.data.decode('utf-8')
                    barcode_type = barcode.type  
                    
                    if barcode_type == 'QRCODE':
                        continue
                    elif barcode_type == 'I25':
                        barcode_type = 'ITF14' if len(scanned_barcode_raw) == 14 else 'ITF'
                    elif barcode_type == 'EAN13':
                        if len(scanned_barcode_raw) == 13 and scanned_barcode_raw.startswith('0'):
                            barcode_type = 'UPCA'
                            scanned_barcode_raw = scanned_barcode_raw[1:] 
                        else:
                            barcode_type = 'EAN13'

                    print("\n" + "="*50)
                    print(f"[BARCODE SUCCESS]\n[{barcode_type}] | {scanned_barcode_raw}\n")
                    
                    (bx, by, bw_box, bh_box) = barcode.rect
                    cv2.rectangle(frame, (bx, by), (bx + bw_box, by + bh_box), (0, 0, 255), max(1, int(2 * skala)))
                    
                    teks_barcode = f"[{barcode_type}] {scanned_barcode_raw}"
                    pos_y_barcode = max(by - pad_y_box, min_y_batas)
                    
                    cv2.putText(frame, teks_barcode, (bx, pos_y_barcode), cv2.FONT_HERSHEY_SIMPLEX, fs_standar, (0, 0, 0), thick_tebal, cv2.LINE_AA)
                    cv2.putText(frame, teks_barcode, (bx, pos_y_barcode), cv2.FONT_HERSHEY_SIMPLEX, fs_standar, (0, 255, 255), thick_sedang, cv2.LINE_AA)
                    
                    # Dokumentasi Kanan Atas (Hanya FPS)
                    cv2.putText(frame, f"FPS: {self.fps:.2f}", (w - pad_x_kanan, pad_y_fps), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 0, 0), thick_tebal, cv2.LINE_AA)
                    cv2.putText(frame, f"FPS: {self.fps:.2f}", (w - pad_x_kanan, pad_y_fps), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 255, 0), thick_tipis, cv2.LINE_AA)
                    
                    waktu_sekarang = datetime.now().strftime("%Y%m%d_%H%M%S")
                    nama_file_barcode = f"{waktu_sekarang}_barcode_{scanned_barcode_raw}.jpg"
                    
                    waktu_selesai_ai = time.time()
                    durasi_proses_ai = waktu_selesai_ai - waktu_mulai_ai
                    durasi_total = waktu_selesai_ai - waktu_antri
                    
                    print(f"[BARCODE TIMING] Durasi Proses AI: {durasi_proses_ai:.2f} detik")
                    print(f"[BARCODE TIMING] Durasi Total (Sejak Tombol): {durasi_total:.2f} detik")
                    print(f"{nama_file_barcode} Tersimpan di folder: {self.output_folder}")
                    print("="*50)

                    cv2.imwrite(os.path.join(self.output_folder, nama_file_barcode), frame)
                    self.window.after(0, self.ui_update_barcode_success, scanned_barcode_raw)
                    barcode_success = True
                    break
                
                if not barcode_success:
                    self.is_processing_ai = False

            elif task_type == 'TANGGAL':
                barcode_id = task['barcode']
                results = self.model(frame, conf=0.35, verbose=False)
                date_success = False

                for result in results:
                    if date_success: break
                    boxes = result.boxes
                    for box in boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        
                        crop_x1, crop_y1 = max(0, x1 - 8), max(0, y1 - 8)
                        crop_x2, crop_y2 = min(w, x2 + 8), min(target_h, y2 + 8)
                        cropped_img = frame[crop_y1:crop_y2, crop_x1:crop_x2]

                        if cropped_img.size > 0:
                            gray_crop = cv2.cvtColor(cropped_img, cv2.COLOR_BGR2GRAY)
                            resized_crop = cv2.resize(gray_crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                            _, threshold_crop = cv2.threshold(resized_crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                            
                            # custom_config = r'--oem 3 --psm 7 -c preserve_interword_spaces=1 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ./-:'
                            # Tambahkan spasi di awal whitelist, dan ubah psm 7 menjadi psm 6
                            custom_config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1 -c tessedit_char_whitelist= 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ./-:'
                            text_detected = pytesseract.image_to_string(resized_crop, config=custom_config).strip()
                            # text_detected = pytesseract.image_to_string(threshold_crop, config=custom_config).strip()
                            ocr_raw_text = text_detected if text_detected else "EMPTY OCR"

                            if text_detected:
                                print("\n" + "="*50)
                                print(f"[OCR RAW TEXT] Terbaca : {text_detected}")
                                hasil_konversi = date_standard(text_detected)
                                
                                if hasil_konversi is not None:
                                    print(f"[SUCCESS] 🟢 Sukses Konversi : {hasil_konversi}\n")

                                    conf_score = float(box.conf[0])
                                    label_name = self.model.names[int(box.cls[0])]
                                    teks_display = f"{label_name} {conf_score:.2f} | RAW: {ocr_raw_text} | {hasil_konversi}"
                                    pos_y_date = max(y1 - pad_y_box, min_y_batas)
                                    
                                    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), max(1, int(2 * skala)))
                                    cv2.putText(frame, teks_display, (x1, pos_y_date), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 0, 0), thick_tebal, cv2.LINE_AA)
                                    cv2.putText(frame, teks_display, (x1, pos_y_date), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 255, 0), thick_sedang, cv2.LINE_AA)

                                    cv2.putText(frame, f"FPS: {self.fps:.2f}", (w - pad_x_kanan, pad_y_fps), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 0, 0), thick_tebal, cv2.LINE_AA)
                                    cv2.putText(frame, f"FPS: {self.fps:.2f}", (w - pad_x_kanan, pad_y_fps), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 255, 0), thick_tipis, cv2.LINE_AA)

                                    waktu_sekarang = datetime.now().strftime("%Y%m%d_%H%M%S")
                                    tanggal_clean = hasil_konversi.replace("/", "-")
                                    nama_file_tanggal = f"{waktu_sekarang}_tanggal_{barcode_id}_{tanggal_clean}.jpg"

                                    waktu_selesai_ai = time.time()
                                    durasi_proses_ai = waktu_selesai_ai - waktu_mulai_ai
                                    durasi_total = waktu_selesai_ai - waktu_antri

                                    print(f"[TANGGAL TIMING] Durasi Proses AI: {durasi_proses_ai:.2f} detik")
                                    print(f"[TANGGAL TIMING] Durasi Total (Sejak Tombol): {durasi_total:.2f} detik")
                                    print("="*50)

                                    cv2.imwrite(os.path.join(self.output_folder, nama_file_tanggal), frame)
                                    print(f"{nama_file_tanggal} Tersimpan di folder: {self.output_folder}")
                                    print("="*50)
                                    self.window.after(0, self.ui_update_date_success, hasil_konversi)
                                    date_success = True
                                    break
                                else:
                                    print(f"[FAILED]  🔴 Gagal Standarisasi")
                                    print("="*50)

                                    current_time = time.time()
                                    if current_time - self.last_failed_save_time > 2.0:
                                        conf_score = float(box.conf[0])
                                        label_name = self.model.names[int(box.cls[0])]
                                        teks_fail = f"FAIL STD | {label_name} {conf_score:.2f} | RAW: {ocr_raw_text}"
                                        pos_y_date = max(y1 - pad_y_box, min_y_batas)

                                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), max(1, int(2 * skala))) 
                                        cv2.putText(frame, teks_fail, (x1, pos_y_date), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 0, 0), thick_tebal, cv2.LINE_AA)
                                        cv2.putText(frame, teks_fail, (x1, pos_y_date), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 255, 255), thick_sedang, cv2.LINE_AA)

                                        cv2.putText(frame, f"FPS: {self.fps:.2f}", (w - pad_x_kanan, pad_y_fps), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 0, 0), thick_tebal, cv2.LINE_AA)
                                        cv2.putText(frame, f"FPS: {self.fps:.2f}", (w - pad_x_kanan, pad_y_fps), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 255, 0), thick_tipis, cv2.LINE_AA)

                                        waktu_sekarang = datetime.now().strftime("%Y%m%d_%H%M%S")
                                        nama_file_gagal = f"{waktu_sekarang}_fail_std_{barcode_id}_raw_{ocr_raw_text}.jpg"
                                        cv2.imwrite(os.path.join(self.output_folder, nama_file_gagal), frame)
                                        print(f"{nama_file_gagal} Tersimpan di folder: {self.output_folder}")
                                        print("="*50)

                                        self.last_failed_save_time = current_time
                            else:
                                current_time = time.time()
                                if current_time - self.last_failed_save_time > 2.0:
                                    conf_score = float(box.conf[0])
                                    label_name = self.model.names[int(box.cls[0])]
                                    teks_fail = f"FAIL OCR | {label_name} {conf_score:.2f} | NO TEXT"
                                    pos_y_date = max(y1 - pad_y_box, min_y_batas)

                                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), max(1, int(2 * skala)))
                                    cv2.putText(frame, teks_fail, (x1, pos_y_date), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 0, 0), thick_tebal, cv2.LINE_AA)
                                    cv2.putText(frame, teks_fail, (x1, pos_y_date), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 0, 255), thick_sedang, cv2.LINE_AA)

                                    cv2.putText(frame, f"FPS: {self.fps:.2f}", (w - pad_x_kanan, pad_y_fps), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 0, 0), thick_tebal, cv2.LINE_AA)
                                    cv2.putText(frame, f"FPS: {self.fps:.2f}", (w - pad_x_kanan, pad_y_fps), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 255, 0), thick_tipis, cv2.LINE_AA)

                                    waktu_sekarang = datetime.now().strftime("%Y%m%d_%H%M%S")
                                    nama_file_gagal = f"{waktu_sekarang}_fail_ocr_{barcode_id}.jpg"
                                    cv2.imwrite(os.path.join(self.output_folder, nama_file_gagal), frame)
                                    print(f"{nama_file_gagal} Tersimpan di folder: {self.output_folder}")
                                    print("="*50)
                                    
                                    self.last_failed_save_time = current_time
                
                if not date_success:
                    self.is_processing_ai = False
            
            self.task_queue.task_done()

    # ================== [ ANTARMUKA PENGGUNA ] ===============
    def ui_update_barcode_success(self, barcode_raw):
        self.scanned_barcode = barcode_raw
        self.current_step = "MEMVALIDASI"
        self.is_processing_ai = False
        self.cek_barcode_ke_laravel(self.scanned_barcode)

    def ui_update_date_success(self, hasil_konversi):
        self.scanned_date = hasil_konversi
        self.current_step = "KONFIRMASI"
        self.notif_pesan_teks = f"{self.nama_barang_terbaca}\nTekan 'MID' untuk SIMPAN DATA"
        self.notif_pesan_warna = (219, 152, 52)
        self.tampilkan_tombol_aksi()
        self.is_processing_ai = False

    def sembunyikan_tombol_aksi(self):
        if self.btn_confirm_send: self.btn_confirm_send.place_forget(); self.btn_confirm_send = None
        if self.btn_retry_date: self.btn_retry_date.place_forget(); self.btn_retry_date = None
        if self.btn_cancel_barcode: self.btn_cancel_barcode.place_forget(); self.btn_cancel_barcode = None
        if self.btn_manual_input: self.btn_manual_input.place_forget(); self.btn_manual_input = None
        if self.btn_toggle_scan: self.btn_toggle_scan.place_forget(); self.btn_toggle_scan = None

    
    def mulai_scanning(self):
        if not getattr(self, 'is_ai_ready', False):
            self.notif_pesan_teks = "Sabar, AI sedang inisialisasi..."
            self.notif_pesan_warna = (61, 76, 231) # Merah/Biru Peringatan
            return # Hentikan fungsi jika AI belum siap
        """Memulai proses scanning berdasarkan konteks barcode/tanggal"""
        self.start_scan_time = time.time()
        if self.scanned_barcode == "-":
            self.current_step = "BARCODE"
            print(f"Memulai Pindai Barcode ...")
            self.notif_pesan_teks = "Scanning Barcode... \nPosisikan Kamera"
        else:
            self.current_step = "TANGGAL"
            print(f"Memulai Pindai Tanggl ...")
            self.notif_pesan_teks = "Scanning Tanggal... \nPosisikan Kamera"
        self.notif_pesan_warna = (15, 196, 241)
        self.tampilkan_tombol_scan_ulang_saja()

    def pause_scanning(self):
        """Menghentikan/memause proses scanning"""
        if self.current_step == "BARCODE":
            self.current_step = "IDLE_BARCODE"
            self.notif_pesan_teks = "Pause Barcode. \nTekan 'MID' Lanjut"
        elif self.current_step == "TANGGAL":
            self.current_step = "IDLE_TANGGAL"
            self.notif_pesan_teks = "Pause Tanggal. \nTekan 'MID' Lanjut"
        self.notif_pesan_warna = (230, 126, 34)
        self.tampilkan_tombol_scan_ulang_saja()

    def tampilkan_tombol_scan_ulang_saja(self):
        self.sembunyikan_tombol_aksi()
        
        # Tampilkan tombol Ulangi Pindai hanya jika sudah ada barcode yang discan
        if self.scanned_barcode != "-":
            self.btn_cancel_barcode = tk.Button(self.video_label, text="ULANGI PINDAI", font=("Arial", 9, "bold"), bg="#c0392b", fg="white", command=self.reset_scanner, bd=0)
            self.btn_cancel_barcode.place(x=495, y=375, width=160, height=35)
        
            self.btn_manual_input = tk.Button(self.video_label, text="INPUT MANUAL", font=("Arial", 9, "bold"), bg="#9b59b6", fg="white", command=self.aktifkan_input_manual, bd=0)
            self.btn_manual_input.place(x=320, y=375, width=160, height=35)

        # Tombol Mulai / Pause Scanning tepat di bawah Input Manual (y=420)
        if self.current_step in ["BARCODE", "TANGGAL"]:
            self.btn_toggle_scan = tk.Button(self.video_label, text="PAUSE SCANNING", font=("Arial", 9, "bold"), bg="#f39c12", fg="white", command=self.pause_scanning, bd=0)
        else:
            self.btn_toggle_scan = tk.Button(self.video_label, text="MULAI SCANNING", font=("Arial", 9, "bold"), bg="#27ae60", fg="white", command=self.mulai_scanning, bd=0)
        self.btn_toggle_scan.place(x=320, y=420, width=160, height=35)

    def tampilkan_tombol_aksi(self):
        self.sembunyikan_tombol_aksi()
        self.btn_confirm_send = tk.Button(self.video_label, text="SIMPAN DATA", font=("Arial", 10, "bold"), bg="#3498db", fg="white", command=self.proses_konfirmasi_kirim, bd=0)
        self.btn_confirm_send.place(x=320, y=375, width=160, height=35)

        self.btn_cancel_barcode = tk.Button(self.video_label, text="ULANGI PINDAI", font=("Arial", 9, "bold"), bg="#c0392b", fg="white", command=self.reset_scanner, bd=0)
        self.btn_cancel_barcode.place(x=495, y=375, width=160, height=35)

        self.btn_manual_input = tk.Button(self.video_label, text="INPUT MANUAL", font=("Arial", 9, "bold"), bg="#9b59b6", fg="white", command=self.aktifkan_input_manual, bd=0)
        self.btn_manual_input.place(x=495, y=420, width=160, height=35)

        if self.current_step in ["BARCODE", "TANGGAL"]:
            self.btn_toggle_scan = tk.Button(self.video_label, text="PAUSE SCANNING", font=("Arial", 9, "bold"), bg="#f39c12", fg="white", command=self.pause_scanning, bd=0)
        else:
            self.btn_toggle_scan = tk.Button(self.video_label, text="SCAN TANGGAL", font=("Arial", 9, "bold"), bg="#27ae60", fg="white", command=self.mulai_scanning, bd=0)
        self.btn_toggle_scan.place(x=320, y=420, width=160, height=35)

    def aktifkan_input_manual(self):
        self.sembunyikan_tombol_aksi()
        self.current_step = "MANUAL_INPUT"
        self.current_digit_index = 0

        if self.scanned_date and len(self.scanned_date) == 10 and self.scanned_date != "-":
            try:
                if "/" in self.scanned_date:
                    dd, mm, yyyy = self.scanned_date.split("/")
                else:
                    yyyy, mm, dd = self.scanned_date.split("-")
                self.manual_date_chars = list(f"{dd}{mm}{yyyy}")
            except Exception:
                self.manual_date_chars = list(datetime.now().strftime("%d%m%Y"))
        else:
            self.manual_date_chars = list(datetime.now().strftime("%d%m%Y"))

        self.notif_pesan_teks = "MODE INPUT MANUAL TANGGAL\nMID (OK) | RST (Batal)"
        self.notif_pesan_warna = (230, 126, 34)

        self.btn_confirm_send = tk.Button(self.video_label, text="SELESAI (MID)", font=("Arial", 10, "bold"), bg="#2ecc71", fg="white", command=lambda: self.simulasikan_tombol_fisik("MID"), bd=0)
        self.btn_confirm_send.place(x=320, y=375, width=160, height=35)

        self.btn_cancel_barcode = tk.Button(self.video_label, text="BATAL (RST)", font=("Arial", 9, "bold"), bg="#c0392b", fg="white", command=self.reset_scanner, bd=0)
        self.btn_cancel_barcode.place(x=495, y=375, width=160, height=35)

    # ================== [ KONTROL PERANGKAT KERAS ] ==========
    def init_gpio(self):
        GPIO.setmode(GPIO.BCM)
        for pin_name, pin_num in self.PINS.items():
            GPIO.setup(pin_num, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def baca_tombol_gpio_loop(self):
        if self.current_step == "MANUAL_INPUT":
            if GPIO.input(self.PINS["UP"]) == GPIO.LOW:
                self.ubah_digit_manual(1)
                time.sleep(0.2)
            elif GPIO.input(self.PINS["DWN"]) == GPIO.LOW:
                self.ubah_digit_manual(-1)
                time.sleep(0.2)
            elif GPIO.input(self.PINS["LET"]) == GPIO.LOW:
                self.geser_kursor_manual(-1)
                time.sleep(0.2)
            elif GPIO.input(self.PINS["RHT"]) == GPIO.LOW:
                self.geser_kursor_manual(1)
                time.sleep(0.2)
            elif GPIO.input(self.PINS["MID"]) == GPIO.LOW:
                dd = "".join(self.manual_date_chars[0:2])
                mm = "".join(self.manual_date_chars[2:4])
                yyyy = "".join(self.manual_date_chars[4:8])
                self.scanned_date = f"{dd}/{mm}/{yyyy}"

                self.current_step = "KONFIRMASI"
                self.notif_pesan_teks = f"Barcode: {self.scanned_barcode}\nTekan 'MID' untuk SIMPAN DATA"
                self.notif_pesan_warna = (219, 152, 52)
                self.tampilkan_tombol_aksi()
                time.sleep(0.3)
            elif GPIO.input(self.PINS["RST"]) == GPIO.LOW:
                waktu_mulai = time.time()
                tombol_ditahan = True
                while GPIO.input(self.PINS["RST"]) == GPIO.LOW:
                    self.window.update() 
                    if time.time() - waktu_mulai > 3.0:
                        self.close_application()
                        tombol_ditahan = False
                        return
                if tombol_ditahan:
                    self.reset_scanner()
                time.sleep(0.3)
                
        else:
            if GPIO.input(self.PINS["MID"]) == GPIO.LOW:
                if self.current_step == "IDLE_BARCODE":
                    self.mulai_scanning()
                elif self.current_step == "BARCODE":
                    self.pause_scanning()
                elif self.current_step == "IDLE_TANGGAL":
                    self.mulai_scanning()
                elif self.current_step == "TANGGAL":
                    self.pause_scanning()
                elif self.current_step == "KONFIRMASI":
                    self.proses_konfirmasi_kirim()
                time.sleep(0.3)
            elif GPIO.input(self.PINS["SET"]) == GPIO.LOW and self.current_step in ["IDLE_TANGGAL", "TANGGAL", "KONFIRMASI"]:
                self.aktifkan_input_manual()
                time.sleep(0.3)
            elif GPIO.input(self.PINS["LET"]) == GPIO.LOW and self.current_step == "KONFIRMASI":
                self.retry_date_only()
                time.sleep(0.3)
            elif GPIO.input(self.PINS["RST"]) == GPIO.LOW:
                waktu_mulai = time.time()
                tombol_ditahan = True
                while GPIO.input(self.PINS["RST"]) == GPIO.LOW:
                    self.window.update() 
                    if time.time() - waktu_mulai > 3.0:
                        self.close_application()
                        tombol_ditahan = False
                        return
                if tombol_ditahan:
                    self.reset_scanner()
                time.sleep(0.3)

        self.window.after(50, self.baca_tombol_gpio_loop)

    def ubah_digit_manual(self, nilai):
        temp_chars = list(self.manual_date_chars)
        try:
            current_val = int(temp_chars[self.current_digit_index])
            new_val = (current_val + nilai) % 10
            temp_chars[self.current_digit_index] = str(new_val)

            tanggal_aktif = int("".join(temp_chars[0:2]))
            bulan_aktif = int("".join(temp_chars[2:4]))
            tahun_aktif = int("".join(temp_chars[4:8]))

            if self.current_digit_index in [4, 5, 6, 7]:
                if tahun_aktif < 2020:
                    temp_chars[4], temp_chars[5], temp_chars[6], temp_chars[7] = "2", "0", "9", "9"
                elif tahun_aktif > 2099:
                    temp_chars[4], temp_chars[5], temp_chars[6], temp_chars[7] = "2", "0", "2", "0"
            elif self.current_digit_index in [2, 3]:
                if bulan_aktif > 12:
                    temp_chars[2], temp_chars[3] = ("0", "1") if nilai > 0 else ("1", "2")
                elif bulan_aktif == 0:
                    temp_chars[2], temp_chars[3] = ("1", "2") if nilai < 0 else ("0", "1")
                bulan_aktif = int("".join(temp_chars[2:4]))

            calc_bulan = bulan_aktif if bulan_aktif != 0 else 1
            _, hari_maksimal = monthrange(tahun_aktif, calc_bulan)

            if tanggal_aktif > hari_maksimal or tanggal_aktif == 0:
                if self.current_digit_index in [0, 1] and nilai > 0 and tanggal_aktif != 0:
                    temp_chars[0], temp_chars[1] = "0", "1"
                else:
                    str_max = f"{hari_maksimal:02d}"
                    temp_chars[0], temp_chars[1] = str_max[0], str_max[1]

            self.manual_date_chars = temp_chars
        except ValueError:
            pass

    def geser_kursor_manual(self, arah):
        self.current_digit_index = (self.current_digit_index + arah) % 8

    def simulasikan_tombol_fisik(self, tipe):
        if tipe == "MID":
            dd = "".join(self.manual_date_chars[0:2])
            mm = "".join(self.manual_date_chars[2:4])
            yyyy = "".join(self.manual_date_chars[4:8])
            self.scanned_date = f"{dd}/{mm}/{yyyy}"
            self.current_step = "KONFIRMASI"
            self.notif_pesan_teks = f"Barcode: {self.scanned_barcode}\nTekan 'MID' untuk SIMPAN DATA"
            self.notif_pesan_warna = (219, 152, 52)
            self.tampilkan_tombol_aksi()

    # ====================== [ JARINGAN & API ] =================
    def PingServerLuar(self):
        try:
            requests.head(BASE_SERVER_URL, timeout=1.5)
            return True
        except requests.exceptions.RequestException:
            return False

    def cek_koneksi_berkala(self):
        koneksi_saat_ini = self.PingServerLuar()
        
        if koneksi_saat_ini:
            self.status_koneksi_teks = "Connected"
            self.status_koneksi_warna = (46, 204, 113)
            self.status_koneksi_terakhir = True
        else:
            self.status_koneksi_teks = "Disconnected"
            self.status_koneksi_warna = (60, 76, 231)
            self.status_koneksi_terakhir = False

        # --- MODIFIKASI 2: Tahan pesan jika AI belum siap ---
        if getattr(self, 'is_first_network_check', False):
            self.is_first_network_check = False
            if self.current_step == "IDLE_BARCODE":
                if getattr(self, 'is_ai_ready', False):
                    self.notif_pesan_teks = "Tekan 'MID' untuk Scan Barcode"
                    self.notif_pesan_warna = (230, 126, 34)
                else:
                    self.notif_pesan_teks = "Jaringan OK. AI masih dimuat...\nMohon tunggu."
                    self.notif_pesan_warna = (230, 126, 34)

        self.window.after(4000, self.cek_koneksi_berkala)

    def cek_barcode_ke_laravel(self, barcode):
        self.notif_pesan_teks = "Memvalidasi Produk..."
        self.notif_pesan_warna = (15, 196, 241)
        self.sembunyikan_tombol_aksi()
        self.window.update_idletasks()
        waktu_mulai_cek = time.time()

        try:
            url_cek = f"{LARAVEL_CHECK_URL}/{barcode}"
            response = requests.get(url_cek, timeout=3)
            waktu_selesai_cek = time.time()
            durasi_cek = waktu_selesai_cek - waktu_mulai_cek
            print("\n" + "="*50)
            print(f"[NETWORK TIMING] Durasi Validasi Barcode: {durasi_cek:.2f} detik")
            print("="*50)
            if self.current_step == "IDLE_BARCODE":
                return

            if response.status_code == 200:
                server_data = response.json()
                nama_mentah = server_data.get("data", {}).get("nama_barang", "Produk Terdaftar")
                
                if len(nama_mentah) > 30:
                    self.nama_barang_terbaca = nama_mentah[:27] + "..."
                else:
                    self.nama_barang_terbaca = nama_mentah

                self.notif_pesan_teks = (
                    f"{self.nama_barang_terbaca}\nTekan MID untuk Scan Tanggal"
                )
                self.notif_pesan_warna = (230, 126, 34)
                self.current_step = "IDLE_TANGGAL"
                self.tampilkan_tombol_scan_ulang_saja()
            else:
                self.notif_pesan_teks = "Barang tersebut belum terdaftar!"
                self.notif_pesan_warna = (61, 76, 231)
                self.window.after(1500, self.reset_scanner)
        except requests.exceptions.RequestException:
            self.notif_pesan_teks = "❌ Masalah Validasi Jaringan!"
            self.notif_pesan_warna = (61, 76, 231)
            self.window.after(1500, self.reset_scanner)

    def kirim_ke_laravel(self, barcode, tanggal):
        payload = {"barcode": barcode, "expiry_date": tanggal}
        self.notif_pesan_teks = "Mengirim data..."
        self.notif_pesan_warna = (15, 196, 241)
        self.window.update_idletasks()
        waktu_mulai_kirim = time.time()

        try:
            response = requests.post(LARAVEL_API_URL, json=payload, timeout=4)
            waktu_selesai_kirim = time.time()
            durasi_kirim = waktu_selesai_kirim - waktu_mulai_kirim
            
            print("\n" + "="*50)
            print(f"[NETWORK TIMING] Durasi Simpan Data ke Server: {durasi_kirim:.2f} detik")
            print("="*50)            
            
            try:
                server_data = response.json()
                pesan_server = server_data.get("message", "Data diproses.")
            except ValueError:
                pesan_server = f"Server Error (Kode: {response.status_code})"

            if response.status_code in [200, 201]:
                self.sembunyikan_tombol_aksi()
                self.notif_pesan_teks = f"{pesan_server}\nSiap memindai berikutnya..."
                self.notif_pesan_warna = (113, 204, 46)
                self.window.after(1500, self.reset_scanner)

            elif response.status_code == 409:
                self.sembunyikan_tombol_aksi()
                self.notif_pesan_teks = f"{pesan_server}\nSistem memindai ulang."
                self.notif_pesan_warna = (34, 126, 230)
                self.window.after(2500, self.reset_scanner)

            else:
                self.notif_pesan_teks = f"{pesan_server}"
                self.notif_pesan_warna = (61, 76, 231)
                self.window.after(2500, self.reset_scanner)
                self.tampilkan_tombol_aksi()
                
        except requests.exceptions.RequestException:
            self.notif_pesan_teks = "Gagal terhubung ke server!"
            self.notif_pesan_warna = (61, 76, 231)
            self.tampilkan_tombol_aksi()

    # ================== [ PEMROSESAN UTAMA ] ==================
    def update_pipeline(self):
        if self.is_changing_camera:
            self.window.after(50, self.update_pipeline)
            return

        self.new_frame_time = time.time()
        time_diff = self.new_frame_time - self.prev_frame_time
        self.fps = (1 / time_diff) if time_diff > 0 else 0.0
        self.prev_frame_time = self.new_frame_time

        try:
            frame = self.picam.capture_array()
        except Exception:
            self.window.after(50, self.update_pipeline)
            return

        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        h, w, _ = frame.shape
          
        target_aspect = 800 / 480
        current_aspect = w / h

        if current_aspect > target_aspect:
            target_w = int(h * target_aspect)
            start_x = (w - target_w) // 2
            frame_highres = frame[:, start_x:start_x+target_w]
        else:
            target_h = int(w / target_aspect)
            start_y = (h - target_h) // 2
            frame_highres = frame[start_y:start_y+target_h, :] 
            
        self.last_highres_frame = frame_highres.copy()

        # BARCODE: Mengirim frame asli resolusi tinggi ke antrian AI
        if self.current_step == "BARCODE":
            if not self.is_processing_ai:
                self.is_processing_ai = True
                self.notif_pesan_teks = "Mencari Barcode...\nPosisikan Produk"
                self.notif_pesan_warna = (15, 196, 241)
                
                self.task_queue.put({
                    'task_type': 'BARCODE',
                    'frame': frame_highres.copy(),
                    'dimensions': (frame_highres.shape[1], frame_highres.shape[0]),
                    'enqueue_time': self.start_scan_time
                })

        # TANGGAL: Mengirim frame asli resolusi tinggi ke antrian AI
        elif self.current_step == "TANGGAL":
            if not self.is_processing_ai:
                self.is_processing_ai = True
                self.notif_pesan_teks = "Menganalisis Tanggal...\nMohon Tahan Kamera"
                self.notif_pesan_warna = (15, 196, 241)
                
                self.task_queue.put({
                    'task_type': 'TANGGAL',
                    'frame': frame_highres.copy(),
                    'barcode': self.scanned_barcode,
                    'dimensions': (frame_highres.shape[1], frame_highres.shape[0]),
                    'enqueue_time': self.start_scan_time
                })

        # Frame untuk display GUI diperkecil ke 800x480 agar pas dengan monitor touchscreen
        frame_ui = cv2.resize(frame_highres, (800, 480), interpolation=cv2.INTER_AREA)
        
        guidance_text = self.get_guidance_text()
        if guidance_text:
            cv2.putText(frame_ui, guidance_text, (20, 470), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1, cv2.LINE_AA)
        
        self.current_display_frame = frame_ui.copy()

        # Render UI Layer di layar (800x480)
        cv2.putText(frame_ui, "BARCODE / SKU", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(frame_ui, "BARCODE / SKU", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 189, 195), 2, cv2.LINE_AA)
        cv2.putText(frame_ui, str(self.scanned_barcode), (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(frame_ui, str(self.scanned_barcode), (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        
        cv2.putText(frame_ui, "TANGGAL EXPIRED", (530, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(frame_ui, "TANGGAL EXPIRED", (530, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 189, 195), 2, cv2.LINE_AA)
        
        if self.current_step == "MANUAL_INPUT":
            dd = "".join(self.manual_date_chars[0:2])
            mm = "".join(self.manual_date_chars[2:4])
            yyyy = "".join(self.manual_date_chars[4:8])
            string_tampilan = f"{dd}/{mm}/{yyyy}"
            
            base_x = 530
            cv2.putText(frame_ui, string_tampilan, (base_x, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 5, cv2.LINE_AA)
            cv2.putText(frame_ui, string_tampilan, (base_x, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (46, 204, 113), 2, cv2.LINE_AA)
            
            visual_index = self.current_digit_index
            if self.current_digit_index >= 2: visual_index += 1
            if self.current_digit_index >= 4: visual_index += 1
            
            teks_sebelum_kursor = string_tampilan[:visual_index]
            lebar_sebelum, _ = cv2.getTextSize(teks_sebelum_kursor, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
            lebar_digit_aktif, _ = cv2.getTextSize(string_tampilan[visual_index], cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
            lebar_kursor, _ = cv2.getTextSize("^", cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
            
            kursor_x = base_x + lebar_sebelum + (lebar_digit_aktif // 2) - (lebar_kursor // 2)
            cv2.putText(frame_ui, "^", (kursor_x, 82), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 5, cv2.LINE_AA)
            cv2.putText(frame_ui, "^", (kursor_x, 82), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
        else:
            cv2.putText(frame_ui, str(self.scanned_date), (530, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 5, cv2.LINE_AA)
            cv2.putText(frame_ui, str(self.scanned_date), (530, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

        # Menampilkan FPS
        cv2.putText(frame_ui, f"FPS: {self.fps:.2f}", (710, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(frame_ui, f"FPS: {self.fps:.2f}", (710, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 2, cv2.LINE_AA)
        
        cv2.putText(frame_ui, self.status_koneksi_teks, (20, 365), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(frame_ui, self.status_koneksi_teks, (20, 365), cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.status_koneksi_warna, 2, cv2.LINE_AA)

        lines = self.notif_pesan_teks.split('\n')
        y_offset = 395
        for line in lines:
            cv2.putText(frame_ui, line, (20, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(frame_ui, line, (20, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.55, self.notif_pesan_warna, 2, cv2.LINE_AA)
            y_offset += 25

        self.current_display_frame = frame_ui.copy()

        cv2_image = cv2.cvtColor(frame_ui, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(cv2_image)
        img_tk = ImageTk.PhotoImage(image=pil_img)

        self.video_label.img_tk = img_tk
        self.video_label.configure(image=img_tk)

        self.window.after(10, self.update_pipeline)

    def proses_konfirmasi_kirim(self):
        if self.btn_confirm_send: self.btn_confirm_send.configure(state=tk.DISABLED)
        if self.btn_retry_date: self.btn_retry_date.configure(state=tk.DISABLED)
        if self.btn_cancel_barcode: self.btn_cancel_barcode.configure(state=tk.DISABLED)
        if self.btn_manual_input: self.btn_manual_input.configure(state=tk.DISABLED)
        if self.btn_toggle_scan: self.btn_toggle_scan.configure(state=tk.DISABLED)
        self.kirim_ke_laravel(self.scanned_barcode, self.scanned_date)

    def retry_date_only(self):
        self.sembunyikan_tombol_aksi()
        self.current_step = "IDLE_TANGGAL"
        self.scanned_date = "-"
        self.notif_pesan_teks = f"Barcode: {self.scanned_barcode}\nTekan MID untuk Scan Tanggal" 
        self.notif_pesan_warna = (230, 126, 34)
        self.tampilkan_tombol_scan_ulang_saja()
    
    # ================== [ PEMBERSIHAN & KELUAR ] ==============
    def take_screenshot(self):
        """Mengambil screenshot layar UI (800x480) dengan elemen overlay visual."""
        if hasattr(self, 'current_display_frame') and self.current_display_frame is not None:
            waktu_sekarang = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            nama_file = f"screenshot_{waktu_sekarang}.jpg"
            path_simpan = os.path.join(self.output_folder, nama_file)
            
            cv2.imwrite(path_simpan, self.current_display_frame)
            
            self.temp_notif_teks = self.notif_pesan_teks
            self.temp_notif_warna = self.notif_pesan_warna
            
            self.notif_pesan_teks = f"Screenshot Tersimpan!\n{nama_file}"
            self.notif_pesan_warna = (46, 204, 113) 
            
            self.window.after(2000, self.restore_notification)

    def take_capture_highres(self):
        """Mengambil capture dari resolusi asli kamera dengan overlay FPS di kanan atas."""
        if hasattr(self, 'last_highres_frame') and self.last_highres_frame is not None:
            waktu_sekarang = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            frame_to_save = self.last_highres_frame.copy()
            
            # --- RENDER OVERLAY FPS DI KANAN ATAS ---
            w = frame_to_save.shape[1]
            skala = w / 800.0
            fs_kecil = 0.45 * skala
            thick_tipis = max(1, int(1 * skala))
            thick_tebal = max(2, int(4 * skala))
            pad_x_kanan = int(120 * skala)
            pad_y_fps = int(30 * skala)

            cv2.putText(frame_to_save, f"FPS: {self.fps:.2f}", (w - pad_x_kanan, pad_y_fps), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 0, 0), thick_tebal, cv2.LINE_AA)
            cv2.putText(frame_to_save, f"FPS: {self.fps:.2f}", (w - pad_x_kanan, pad_y_fps), cv2.FONT_HERSHEY_SIMPLEX, fs_kecil, (0, 255, 0), thick_tipis, cv2.LINE_AA)
            
            nama_file = f"capture_raw_{waktu_sekarang}.jpg"
            path_simpan = os.path.join(self.output_folder, nama_file)
            
            cv2.imwrite(path_simpan, frame_to_save)
            
            self.temp_notif_teks = self.notif_pesan_teks
            self.temp_notif_warna = self.notif_pesan_warna
            
            self.notif_pesan_teks = f"Capture High-Res (+FPS) Tersimpan!\n{nama_file}"
            self.notif_pesan_warna = (46, 204, 113)
            
            self.window.after(2000, self.restore_notification)

    def restore_notification(self):
        if "Tersimpan" in self.notif_pesan_teks:
            self.notif_pesan_teks = getattr(self, 'temp_notif_teks', "Siap...")
            self.notif_pesan_warna = getattr(self, 'temp_notif_warna', (255, 255, 255))

    def reset_scanner(self):
        self.current_step = "IDLE_BARCODE"
        self.scanned_barcode = "-"
        self.scanned_date = "-"
        self.nama_barang_terbaca = ""
        self.notif_pesan_teks = "Tekan 'MID' untuk Scan Barcode" 
        self.notif_pesan_warna = (230, 126, 34)
        self.is_processing_ai = False
        self.manual_date_chars = list(datetime.now().strftime("%d%m%Y"))
        self.tampilkan_tombol_scan_ulang_saja()

    def close_application(self):
        self.picam.stop()
        GPIO.cleanup()
        self.window.destroy()

# ================== [ TITIK EKSEKUSI ] ====================
if __name__ == "__main__":
    root = tk.Tk()
    app = SmartScannerApp(root)
    root.mainloop()
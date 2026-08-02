# date_parser.py
import re
import datetime

def date_standard(teks_ocr):
    if not teks_ocr:
        return None

    # 1. Bersihkan teks dari sampah kemasan umum
    teks = teks_ocr.upper()
    teks = re.sub(r'(EXP|MFG|ED|ESF|BB|BEST|BP|EF|ESP|EAP|BEST|BEFORE|PROD|DATE|TANGGAL|KADALUARSA)[:.\s-]*', '', teks)
    teks = re.sub(r'^[A-Z]{1,2}(?=\d+)', '', teks)
    # teks = re.sub(r'^[EP](?=\d+)', '', teks)

    teks = teks.strip()
    
    # 2. Kamus standarisasi bulan ke angka
    bulan_ke_angka = {
        'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04', 'MEI': '05', 'MAY': '05', 
        'JUN': '06', 'JUL': '07', 'AGU': '08', 'AUG': '08', 'SEP': '09', 'OKT': '10',
        'OCT': '10', 'NOV': '11', 'DES': '12', 'DEC': '12'
    }

    # 3. Antisipasi jika huruf pemisah bulan rusak/rapat (misal '13OKT26' atau '13OCT2026')
    # Kita beri spasi secara paksa menggunakan regex sebelum di-split
    for bln in bulan_ke_angka.keys():
        if bln in teks:
            teks = re.sub(f'({bln})', r' \1 ', teks)
            break
            
    # 4. Pecah komponen berdasarkan spasi dan tanda baca
    bagian = [b for b in re.split(r'[\s.\-_/]+', teks) if b]
    
    if not bagian:
        return None

    # Lakukan konversi teks bulan ke angka pada list 'bagian'
    pake_bulan_huruf = False
    for i, part in enumerate(bagian):
        if part in bulan_ke_angka:
            bagian[i] = bulan_ke_angka[part]
            pake_bulan_huruf = True

    try:
        tahun_sekarang = datetime.datetime.now().year 
        tahun_valid_4d = [str(tahun_sekarang + i) for i in range(-6, 9)] 
        tahun_valid_2d = [s[2:] for s in tahun_valid_4d]            

        teks_target = None  # Gunakan variabel baru untuk menampung format target

        # Tambahan
        # =========================================================
        # INTERSEPSI AWAL: JIKA BLOK PERTAMA ADALAH 6/8 DIGIT (Tanggal Nyambung)
        # Akan mengabaikan seluruh sisa array (seperti jam/batch) di belakangnya
        # =========================================================
        if len(bagian[0]) in [6, 8] and bagian[0].isdigit():
            teks_satu = bagian[0]
            if len(teks_satu) == 6:
                if int(teks_satu[0:2]) <= 31 and int(teks_satu[2:4]) <= 12 and teks_satu[4:6] in tahun_valid_2d:
                    teks_target = f"{teks_satu[0:2]}/{teks_satu[2:4]}/20{teks_satu[4:6]}"
                elif teks_satu[0:2] in tahun_valid_2d and int(teks_satu[2:4]) <= 12 and int(teks_satu[4:6]) <= 31:
                    teks_target = f"{teks_satu[4:6]}/{teks_satu[2:4]}/20{teks_satu[0:2]}"
            elif len(teks_satu) == 8:
                if int(teks_satu[0:2]) <= 31 and int(teks_satu[2:4]) <= 12 and teks_satu[4:8] in tahun_valid_4d:
                    teks_target = f"{teks_satu[0:2]}/{teks_satu[2:4]}/{teks_satu[4:8]}"
                elif teks_satu[0:4] in tahun_valid_4d and int(teks_satu[4:6]) <= 12 and int(teks_satu[6:8]) <= 31:
                    teks_target = f"{teks_satu[6:8]}/{teks_satu[4:6]}/{teks_satu[0:4]}"
        # akhir tmbahan

        # =========================================================
        # KONDISI A: JIKA TERBACA 2 BAGIAN (Bulan-Tahun / Tahun-Bulan)
        # =========================================================
        if len(bagian) == 2:
            if bagian[0].isdigit() and bagian[1].isdigit():
                len_p0, len_p1 = len(bagian[0]), len(bagian[1])
                
                # [PRIORITAS 1] Bulan, Tahun (MM YY / MM YYYY)
                if (bagian[1] in tahun_valid_2d or len_p1 == 4) and int(bagian[0]) <= 12:
                    teks_target = f"01/{bagian[0].zfill(2)}/{bagian[1] if len_p1 == 4 else '20'+bagian[1]}"
                
                # [PRIORITAS 2] Tahun, Bulan (YY MM / YYYY MM)
                elif (bagian[0] in tahun_valid_2d or len_p0 == 4) and int(bagian[1]) <= 12:
                    teks_target = f"01/{bagian[1].zfill(2)}/{bagian[0] if len_p0 == 4 else '20'+bagian[0]}"
                
                # [Lainnya] Fallback (Tanggal & Bulan tanpa tahun, misal "15 10" atau "10 15")
                elif len_p0 <= 2 and len_p1 <= 2:
                    # Cek sebagai DD-MM
                    if int(bagian[1]) <= 12 and int(bagian[0]) <= 31: 
                        teks_target = f"{bagian[0].zfill(2)}/{bagian[1].zfill(2)}/{tahun_sekarang}"
                    # Cek sebagai MM-DD (jika DD-MM gagal)
                    elif int(bagian[0]) <= 12 and int(bagian[1]) <= 31:
                        teks_target = f"{bagian[1].zfill(2)}/{bagian[0].zfill(2)}/{tahun_sekarang}"

        # =========================================================
        # KONDISI B: JIKA TERBACA 3 BAGIAN LENGKAP (Hari-Bulan-Tahun)
        # =========================================================
        elif len(bagian) >= 3:
            p0, p1, p2 = bagian[0], bagian[1], bagian[2]

            if p0.isdigit() and p1.isdigit() and p2.isdigit():
                len_p0, len_p2 = len(p0), len(p2)

                # [PRIORITAS 1] Tanggal, Bulan, Tahun (DD MM YY / DD MM YYYY) - STANDAR LOKAL
                if (p2 in tahun_valid_2d or len_p2 == 4) and int(p1) <= 12 and int(p0) <= 31:
                    hari, bulan = p0.zfill(2), p1.zfill(2)
                    tahun = p2 if len_p2 == 4 else f"20{p2}"
                    teks_target = f"{hari}/{bulan}/{tahun}"
                
                # [PRIORITAS 2] Bulan, Tanggal, Tahun (MM DD YY / MM DD YYYY) - FORMAT IMPOR
                # Akan dieksekusi HANYA jika PRIORITAS 1 gagal (angka tengah p1 > 12)
                elif (p2 in tahun_valid_2d or len_p2 == 4) and int(p0) <= 12 and int(p1) <= 31:
                    hari, bulan = p1.zfill(2), p0.zfill(2)
                    tahun = p2 if len_p2 == 4 else f"20{p2}"
                    teks_target = f"{hari}/{bulan}/{tahun}"

                # [PRIORITAS 3] Tahun, Bulan, Tanggal (YYYY MM DD / YY MM DD)
                elif (p0 in tahun_valid_2d or len_p0 == 4) and int(p1) <= 12 and int(p2) <= 31:
                    hari, bulan = p2.zfill(2), p1.zfill(2)
                    tahun = p0 if len_p0 == 4 else f"20{p0}"
                    teks_target = f"{hari}/{bulan}/{tahun}"

        # =========================================================
        # KONDISI C: JIKA ANGKA JALUR MEPET TANPA SPASI (Full Angka)
        # =========================================================
        elif len(bagian) == 1 and bagian[0].isdigit():
            teks_satu = bagian[0]
            # Kriteria Panjang 6 Digit
            if len(teks_satu) == 6:
                if int(teks_satu[0:2]) <= 31 and int(teks_satu[2:4]) <= 12 and teks_satu[4:6] in tahun_valid_2d:
                    teks_target = f"{teks_satu[0:2]}/{teks_satu[2:4]}/20{teks_satu[4:6]}"
                elif teks_satu[0:2] in tahun_valid_2d and int(teks_satu[2:4]) <= 12 and int(teks_satu[4:6]) <= 31:
                    teks_target = f"{teks_satu[4:6]}/{teks_satu[2:4]}/20{teks_satu[0:2]}"
            
            # Kriteria Panjang 8 Digit
            elif len(teks_satu) == 8:
                if int(teks_satu[0:2]) <= 31 and int(teks_satu[2:4]) <= 12 and teks_satu[4:8] in tahun_valid_4d:
                    teks_target = f"{teks_satu[0:2]}/{teks_satu[2:4]}/{teks_satu[4:8]}"
                elif teks_satu[0:4] in tahun_valid_4d and int(teks_satu[4:6]) <= 12 and int(teks_satu[6:8]) <= 31:
                    teks_target = f"{teks_satu[6:8]}/{teks_satu[4:6]}/{teks_satu[0:4]}"

        # Jika teks_target gagal terbentuk (karena format aneh/rusak seperti '3X26'), langsung tolak!
        if not teks_target:
            return None

        # 4. Eksekusi verifikasi keaslian kalender menggunakan strptime
        parsed_date = datetime.datetime.strptime(teks_target, "%d/%m/%Y")
        
        # Proteksi tambahan: Pastikan tahun hasil scan masuk akal (6 tahun ke depan dari sekarang)
        if str(parsed_date.year) not in tahun_valid_4d:
            return None
        # =========================================================
        # TAMBAHAN BARU: PROTEKSI EXPIRED KETAT (HARI, BULAN, TAHUN)
        # =========================================================
        # tanggal_hari_ini = datetime.datetime.now().date()
        
        # # Jika tanggal yang dibaca (parsed_date) LEBIH KECIL dari hari ini, tolak!
        # if parsed_date.date() < tanggal_hari_ini:
        #     return None
        # =========================================================
        return parsed_date.strftime("%d/%m/%Y")

    except Exception:
        return None

if __name__ == "__main__":
    # Kumpulan sampel uji yang mewakili berbagai kondisi di lapangan
    sampel_uji = {
        "1. Format 3 Bagian Normal": [
            "EXP 15/10/26",          # Diharapkan: 15/10/2026
            "ED: 25.12.2027",        # Diharapkan: 25/12/2027
            "MFG 28-02-24",          # Diharapkan: 28/02/2024
            "BEST BEFORE 2028/05/10" # Diharapkan: 10/05/2028 (YYYY/MM/DD)
        ],
        "2. Format dengan Huruf Bulan": [
            "15 OKT 26",             # Diharapkan: 15/10/2026
            "12AUG2027",             # Diharapkan: 12/08/2027 (Kondisi huruf rapat)
            "EXP: 05-MEI-28"         # Diharapkan: 05/05/2028
        ],
        "3. Format 2 Bagian (Bulan-Tahun)": [
            "11 26",                 # Diharapkan: 01/11/2026
            "2027 10",               # Diharapkan: 01/10/2027
            "ED OCT 28"              # Diharapkan: 01/10/2028
        ],
        "4. Format Angka Rapat (6 atau 8 digit)": [
            "151026",                # Diharapkan: 15/10/2026 (DDMMYY)
            "271015",                # Diharapkan: 15/10/2027 (YYMMDD)
            "15102028",              # Diharapkan: 15/10/2028 (DDMMYYYY)
            "20291015"               # Diharapkan: 15/10/2029 (YYYYMMDD)
        ],
        "5. Format Tidak Valid (Ditolak / None)": [
            "29/02/26",              # Diharapkan: None (2026 bukan kabisat)
            "15 10 2020",            # Diharapkan: None (Tahun 2020 di luar batas range 2024-2031)
            "EXP 3X26",              # Diharapkan: None (Format rusak)
            "KADALUARSA"             # Diharapkan: None (Tidak ada angka)
        ],
        "6. Format Bulan-Tanggal-Tahun (Impor/US)": [
            "10/25/26",              # Bulan 10, Tanggal 25. Saat ini kodemu akan MENGHASILKAN NONE
            "OCT 25 2026"            # Saat ini kodemu akan MENGHASILKAN NONE
        ],
        "7. Format Hari-Bulan / Bulan-Hari (Tanpa Tahun)": [
            "15 10",                 # Hari 15, Bulan 10. (Fallback Kondisi A)
            "10 15",                 # Bulan 10, Hari 15. 
            "15 OCT"
        ]
    }

    print("=== HASIL PENGUJIAN DATE PARSER ===")
    for kategori, daftar_teks in sampel_uji.items():
        print(f"\n{kategori}")
        print("-" * 40)
        for teks in daftar_teks:
            hasil = date_standard(teks)
            status = "BERHASIL" if hasil else "DITOLAK (None)"
            print(f"Input: {teks:<25} | Output: {str(hasil):<12} | {status}")
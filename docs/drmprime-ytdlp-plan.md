# RoxyTube: yt-dlp terbaru, MPV GPU, dan rencana DRM PRIME

## Tujuan

Membuat RoxyTube di HG680P (Amlogic S905X, Armbian Noble ARM64) lebih andal saat mengambil stream YouTube dan menyiapkan jalur playback hardware yang dapat diuji menuju DRM PRIME, tanpa mengganti antarmuka RoxyTube atau merusak Safe Area.

## Basis branch dan batas perubahan

- Branch eksperimen: `feat/mpv-drmprime-ytdlp`
- Basis: `baseline/1080p-working-7764896`
- Baseline commit: `7764896199d70a18c6766cffd6112c2c95276ecf`
- Branch baseline tidak diubah.
- Tidak mengubah kernel, firmware, driver, Xorg, Openbox, GLAMOR, Kodi, atau instalasi MPV/FFmpeg sistem.

## Perubahan pada branch ini

### 1. yt-dlp terbaru khusus RoxyTube

- `scripts/install-yt-dlp.sh` mengambil release resmi terbaru dari GitHub yt-dlp.
- Memilih binary resmi `yt-dlp_linux_aarch64` untuk HG680P.
- Mengunduh `SHA2-256SUMS` dari release yang sama dan memverifikasi SHA-256 sebelum memasang.
- Instalasi dilakukan tanpa sudo ke:
  `~/.local/share/roxy-youtube-tv/bin/yt-dlp`
- Tidak mengganti `/usr/bin/yt-dlp` atau konfigurasi yt-dlp sistem.
- Aplikasi memprioritaskan binary app-local tersebut; bila belum terpasang, aplikasi tetap memakai yt-dlp dari PATH.
- MPV juga diberi PATH yang memuat direktori binary yang sama, supaya MPV ytdl hook tidak diam-diam memakai yt-dlp sistem yang lama.

Release resmi terbaru yang diperiksa saat penulisan plan: `2026.11.23`. Installer mengambil tag latest secara dinamis saat dijalankan, bukan mengunci versi ini.

Jalankan satu kali sebagai user `roxy`:

```bash
cd /home/Applications/RoxyTube
sh scripts/install-yt-dlp.sh
```

### 2. Kualitas YouTube

- Menambahkan pilihan maksimum `1080p`.
- Auto tetap dapat memilih format sampai 1080p sesuai format yang tersedia.
- Default UI yang sudah ada tidak dipaksa berubah dari 720p; 1080p dapat dipilih secara eksplisit setelah perangkat diuji.
- Jika pemutaran 1080p gagal dimulai, fallback kualitas turun ke 720p, 480p, lalu Auto.
- Kualitas yang dipilih tetap merupakan batas maksimum, bukan jaminan bahwa YouTube menyediakan format tersebut.

### 3. MPV GPU + V4L2 sebagai jalur transisi

Sebelumnya RoxyTube menjalankan MPV dengan `--vo=x11` dan tidak menentukan hwdec secara eksplisit. Pengujian manual di HG680P telah berhasil menampilkan video bergerak menggunakan:

```text
--hwdec=v4l2m2m-copy
--vo=gpu
--gpu-context=x11egl
--gpu-api=opengl
```

Branch ini menyelaraskan opsi MPV embedded dengan jalur yang sudah pernah berhasil diuji tersebut. Nilai default dapat dioverride tanpa mengedit source:

- `ROXY_MPV`
- `ROXY_MPV_HWDEC` (default saat ini: `v4l2m2m-copy`)
- `ROXY_MPV_VO` (default: `gpu`)
- `ROXY_MPV_GPU_CONTEXT` (default: `x11egl`)
- `ROXY_MPV_GPU_API` (default: `opengl`)
- `ROXY_MPV_GPU_HWDEC_INTEROP` (opsional; kosong pada build saat ini)
- `ROXY_YT_DLP` untuk memilih binary yt-dlp secara eksplisit.

**Penting:** `v4l2m2m-copy` tetap jalur copy. Perubahan ini mengaktifkan GPU renderer yang telah diuji bersama V4L2, tetapi belum mengaktifkan zero-copy DRM PRIME.

### 4. Rencana DRM PRIME

Target pipeline:

```text
YouTube URL
   -> yt-dlp terbaru
   -> MPV / FFmpeg
   -> V4L2 meson-vdec (S905X)
   -> AV_PIX_FMT_DRM_PRIME / DMA-BUF
   -> MPV GPU interop
   -> X11 EGL child window RoxyTube
```

Upstream FFmpeg V4L2 M2M umumnya mengeluarkan frame hasil copy ke system memory; dukungan ekspor DMA-BUF/DRM PRIME yang dibutuhkan MPV berada pada fork/patch FFmpeg tertentu. MPV sendiri sudah memiliki dukungan konsumsi DRM PRIME DMA-BUF, tetapi harus menerima buffer yang diekspor dengan format dan modifier yang sesuai.

Referensi teknis:
- MPV V4L2 DRM PRIME: https://github.com/mpv-player/mpv/wiki/V4L2-drmprime-support
- Proyek S905X/Armbian pembanding: https://github.com/dogukangecko/kodi-hwdec-amlogic-armbian
- Patch V4L2 DRM PRIME LibreELEC: https://github.com/LibreELEC/LibreELEC.tv/tree/master/packages/multimedia/ffmpeg/patches/v4l2-drmprime
- MPV manual (DRM PRIME overlay dan plane): https://mpv.io/manual/stable/

Patch dari proyek S905X lama ditujukan untuk FFmpeg 4.4.x dan tidak boleh diasumsikan cocok dengan FFmpeg 6.1.1 milik HG680P. Untuk eksperimen ini, source dipin ke FFmpeg Amlogic fork commit `ad8c2e36ee2d5a30442f6e4ca0e82df2622f8958` (branch `armsoc-9.0.2`) dan patch DRM PRIME LibreELEC dipin ke commit `ceb19682c636ace4d7403d430e7a76c990c62db7`. Pemeriksaan otomatis di GitHub Actions sudah memastikan patch tersebut dapat diterapkan bersih pada source FFmpeg yang dipin.

Build terisolasi sekarang disiapkan:
- `scripts/check-drmprime-patch.sh`: cek kompatibilitas patch yang reproducible.
- `scripts/build-drmprime-runtime.sh`: build FFmpeg dengan V4L2 M2M + libdrm, lalu MPV `v0.42.0` dengan EGL/X11/OpenGL. Hasilnya dibungkus sebagai runtime terpisah.
- `.github/workflows/build-drmprime-runtime.yml`: build ARM64 di GitHub Actions dan unggah artifact selama 14 hari.

Build ini tidak mengubah FFmpeg/MPV sistem. Build workflow harus selesai dan artifact harus lolos pemeriksaan sebelum runtime dicoba di HG680P.

Untuk MPV hasil build yang sudah terbukti menyediakan non-copy V4L2 DRM PRIME, konfigurasi opt-in RoxyTube yang dituju adalah:

```bash
ROXY_MPV="$HOME/.local/share/roxy-youtube-tv/runtime/bin/mpv" \
ROXY_MPV_HWDEC=v4l2m2m \
ROXY_MPV_GPU_HWDEC_INTEROP=drmprime
```

Mode tersebut belum diaktifkan sebagai default dan belum diuji di HG680P. Renderer tetap `gpu + x11egl` agar MPV tetap berada di child window RoxyTube; jangan memakai `vo=drm`/direct KMS karena dapat melewati jendela Qt dan Safe Area.

Langkah berikutnya setelah artifact tersedia:
1. Pasang runtime ke direktori app-local tanpa mengganti binary sistem.
2. Verifikasi `mpv --hwdec=help` menampilkan non-copy `v4l2m2m`, dan `mpv --gpu-hwdec-interop=help` menampilkan `drmprime`.
3. Uji video H.264 1080p pada X11 child window dan pastikan log menampilkan `drm_prime[nv12]` (atau format DRM PRIME yang sesuai).
4. Ukur CPU, frame-drop, seek, subtitle, audio, dan Safe Area sebelum menjadikan mode ini default.

### 5. Safe Area dan integrasi antarmuka

Safe Area yang sudah ada dipertahankan:
- RoxyTube/Qt tetap memiliki jendela utama dan menentukan geometri playback Safe Area dari `~/.config/roxy-display/safe-area.json`.
- MPV tetap tertanam di native child window melalui `--wid`.
- Renderer GPU tidak boleh meminta fullscreen KMS, mengganti mode layar, atau mengubah Xorg/Openbox.
- Tombol Safe Area, kontrol playback, mini-player, dan navigasi remote tetap milik RoxyTube.

Jalur DRM PRIME berbasis overlay DRM langsung dapat melewati jendela X11 dan berpotensi merusak Safe Area. Karena itu, jalur overlay langsung bukan default untuk branch ini; interop EGL/X11 harus dievaluasi terlebih dahulu.

## Pengujian dan kriteria selesai

Pada HG680P, jalankan RoxyTube sebagai user `roxy` dan verifikasi:

1. `~/.local/share/roxy-youtube-tv/bin/yt-dlp --version` menampilkan versi terbaru yang dipasang.
2. Pencarian Home, Trending, dan Search bekerja menggunakan binary app-local.
3. MPV hook juga menggunakan binary app-local (bukan `/usr/bin/yt-dlp`).
4. Video H.264 1080p dapat dipilih; catat resolusi/fps aktual yang diputar.
5. Log MPV menunjukkan V4L2 hardware decoder dan `VO: [gpu]`.
6. Safe Area tetap mengikuti margin konfigurasi, kontrol tetap terlihat/tersembunyi seperti sebelumnya, dan Back/minimize/restore tidak merusak geometri.
7. Bandingkan CPU, RAM, frame-drop, dan kestabilan pada durasi yang sama antara software decode, V4L2 copy, dan DRM PRIME.
8. Uji 10-15 menit serta seek, subtitle, next-video, dan kembali ke Home.

DRM PRIME baru dianggap selesai jika log membuktikan frame DRM PRIME diterima oleh MPV dan hasil playback terukur lebih baik. Keberhasilan mengaktifkan V4L2 saja bukan bukti zero-copy.

## Status saat ini

- [x] Branch eksperimen dibuat dari baseline yang dipilih.
- [x] Installer yt-dlp ARM64 app-local dengan verifikasi checksum ditambahkan.
- [x] Aplikasi memprioritaskan yt-dlp app-local.
- [x] MPV ytdl hook diarahkan ke PATH yang memuat yt-dlp app-local.
- [x] Pilihan kualitas 1080p dan fallback ditambahkan.
- [x] MPV embedded diarahkan ke GPU EGL/X11 dengan V4L2 copy sebagai jalur transisi.
- [x] Override interop GPU DRM PRIME disediakan, tetapi tidak aktif pada build saat ini.
- [x] Safe Area lama dipertahankan.
- [ ] Uji syntax dan installer di CI.
- [ ] Jalankan installer dan playback di HG680P.
- [x] Pin source FFmpeg Amlogic dan patch LibreELEC; CI memastikan patch dapat diterapkan.
- [x] Siapkan build script dan GitHub Actions ARM64 untuk runtime terisolasi.
- [ ] Selesaikan build artifact FFmpeg/MPV DRM PRIME.
- [ ] Uji zero-copy DRM PRIME di HG680P.

"""OCI Always Free Ampere A1 (4 OCPU / 24GB RAM) Auto-Retry Instance Hunter.
Tự động gửi yêu cầu tạo máy chủ VPS liên tục cho đến khi thành công.
Tự động cấu hình cài đặt NovelReader qua cloud-init (user_data) khi máy chủ khởi động.
"""
import base64
import os
import sys
import time
from pathlib import Path

# Fix UTF-8 display on Windows CMD
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import oci

# Cấu hình mặc định đã được trích xuất từ tài khoản Oracle Cloud Singapore
CONFIG_PATH = Path("C:/Users/trung/.oci/config")
DEFAULT_SUBNET_ID = "ocid1.subnet.oc1.ap-singapore-1.aaaaaaaavc7ew3xcr5zmi2xpyven7q2yklahbrurfkhhtzsa5usfx6zuoekq"
DEFAULT_AD_NAME = "Qpri:AP-SINGAPORE-1-AD-1"
DEFAULT_IMAGE_ID = "ocid1.image.oc1.ap-singapore-1.aaaaaaaaw75ef2chh5goomskvdznqz36cadczqelqvndbqcozc5icyig57za" # Ubuntu 24.04 ARM
DEFAULT_SSH_KEY_PUB = Path("C:/Users/trung/Downloads/ssh-key-2026-10-20.key.pub")
DEFAULT_SSH_KEY_PRIV = Path("C:/Users/trung/Downloads/ssh-key-2026-10-20.key")

CLOUD_INIT_SCRIPT = """#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive

# 1. Mo port 8000 trong iptables
iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT || true
netfilter-persistent save 2>/dev/null || true

# 2. Doi khoa apt nếu he thong dang cap nhat ngam
while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do sleep 3; done

apt-get update -y
apt-get install -y software-properties-common git ffmpeg espeak-ng libgomp1 python3-pip

# 3. Cai dat Python 3.11
add-apt-repository -y ppa:deadsnakes/ppa || true
apt-get update -y
apt-get install -y python3.11 python3.11-venv python3.11-dev

# 4. Clone repo NovelReader
TARGET_DIR="/home/ubuntu/NovelReader_Translate"
if [ ! -d "$TARGET_DIR" ]; then
    git clone https://github.com/dungbeommm/NovelReader_Translate.git "$TARGET_DIR"
    chown -R ubuntu:ubuntu "$TARGET_DIR"
fi

cd "$TARGET_DIR"
sudo -u ubuntu python3.11 -m venv .venv
sudo -u ubuntu /home/ubuntu/NovelReader_Translate/.venv/bin/pip install --upgrade pip
sudo -u ubuntu /home/ubuntu/NovelReader_Translate/.venv/bin/pip install -r requirements.txt

# 5. Tai truoc model dich va giong doc
sudo -u ubuntu PYTHONUTF8=1 /home/ubuntu/NovelReader_Translate/.venv/bin/python scripts/download_model.py --model HachimiMT-60-QT || true
sudo -u ubuntu PYTHONUTF8=1 /home/ubuntu/NovelReader_Translate/.venv/bin/python scripts/download_voices.py --default-only || true

# 6. Cai dat systemd service chay tu dong
cat << 'SERVICE_CONF' > /etc/systemd/system/novelreader.service
[Unit]
Description=NovelReader Web Service
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/NovelReader_Translate
Environment="PATH=/home/ubuntu/NovelReader_Translate/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
Environment="PYTHONUTF8=1"
Environment="ALLOWED_HOSTS=*"
ExecStart=/home/ubuntu/NovelReader_Translate/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE_CONF

systemctl daemon-reload
systemctl enable novelreader
systemctl start novelreader
echo "NovelReader setup completed successfully!" > /home/ubuntu/setup_done.txt
"""

def launch_hunter(
    ocpus=4,
    ram_gb=24,
    delay_seconds=45,
    subnet_id=DEFAULT_SUBNET_ID,
    ad_name=DEFAULT_AD_NAME,
    image_id=DEFAULT_IMAGE_ID,
    ssh_pub_path=DEFAULT_SSH_KEY_PUB
):
    print("=" * 65)
    print("     OCI AMPERE A1 AUTO-RETRY HUNTER (NovelReader VPS)")
    print("=" * 65)

    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(f"Không tìm thấy file OCI config: {CONFIG_PATH}")

    config = oci.config.from_file(str(CONFIG_PATH), "DEFAULT")
    compartment_id = config["tenancy"]
    compute_client = oci.core.ComputeClient(config)
    vn_client = oci.core.VirtualNetworkClient(config)

    # Đọc SSH Key
    if not ssh_pub_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy SSH public key: {ssh_pub_path}")
    ssh_public_key = ssh_pub_path.read_text(encoding="utf-8").strip()

    # Encode user_data sang Base64
    user_data_b64 = base64.b64encode(CLOUD_INIT_SCRIPT.encode("utf-8")).decode("utf-8")

    instance_name = "novelreader-vps"
    shape = "VM.Standard.A1.Flex"
    shape_config = oci.core.models.LaunchInstanceShapeConfigDetails(
        ocpus=float(ocpus),
        memory_in_gbs=float(ram_gb)
    )
    source_details = oci.core.models.InstanceSourceViaImageDetails(
        image_id=image_id,
        boot_volume_size_in_gbs=50
    )
    create_vnic_details = oci.core.models.CreateVnicDetails(
        subnet_id=subnet_id,
        assign_public_ip=True,
        display_name=f"{instance_name}-vnic"
    )

    launch_details = oci.core.models.LaunchInstanceDetails(
        compartment_id=compartment_id,
        availability_domain=ad_name,
        display_name=instance_name,
        shape=shape,
        shape_config=shape_config,
        source_details=source_details,
        create_vnic_details=create_vnic_details,
        metadata={
            "ssh_authorized_keys": ssh_public_key,
            "user_data": user_data_b64
        }
    )

    print(f"[*] Khu vực (Region): {config.get('region')}")
    print(f"[*] Phân vùng (AD):   {ad_name}")
    print(f"[*] Cấu hình yêu cầu: {ocpus} OCPU, {ram_gb} GB RAM (Always Free Max)")
    print(f"[*] Tự động cài đặt:  Python 3.11, CTranslate2, Piper, NovelReader Web UI (Port 8000)")
    print(f"[*] Tần suất thử:     Mỗi {delay_seconds} giây")
    print(f"[*] Nhấn Ctrl+C để dừng bất kỳ lúc nào.\n" + "-" * 65)

    attempt = 0
    while True:
        attempt += 1
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now_str}] [Lượt {attempt}] Đang yêu cầu tạo máy chủ...", end=" ", flush=True)

        try:
            response = compute_client.launch_instance(launch_details)
            instance = response.data
            print("\n" + "=" * 65)
            print("🎉 TẠO MÁY CHỦ THÀNH CÔNG! 🎉")
            print(f"Instance ID:   {instance.id}")
            print(f"Display Name:  {instance.display_name}")
            print("=" * 65)
            print("[*] Đang chờ máy chủ cấp phát Public IP và hoàn tất khởi động...")

            public_ip = None
            for _ in range(30):
                time.sleep(5)
                inst = compute_client.get_instance(instance.id).data
                if inst.lifecycle_state == "RUNNING":
                    attachments = compute_client.list_vnic_attachments(compartment_id, instance_id=instance.id).data
                    if attachments:
                        vnic = vn_client.get_vnic(attachments[0].vnic_id).data
                        if vnic.public_ip:
                            public_ip = vnic.public_ip
                            break

            print("\n" + "=" * 65)
            print(f"🌐 PUBLIC IP CỦA BẠN: {public_ip}")
            print(f"🔗 TRANG WEB NOVELREADER: http://{public_ip}:8000")
            print(f"🔑 LỆNH SSH: ssh -i \"{DEFAULT_SSH_KEY_PRIV}\" ubuntu@{public_ip}")
            print("=" * 65)
            print("[!] Lưu ý: Máy chủ sẽ mất khoảng 2-3 phút sau khi bật để hoàn tất cài đặt ngầm.")
            
            with open("vps_info.txt", "w", encoding="utf-8") as f:
                f.write(f"PUBLIC_IP={public_ip}\nINSTANCE_ID={instance.id}\nWEB_URL=http://{public_ip}:8000\n")

            return instance

        except oci.exceptions.ServiceError as exc:
            msg = exc.message or str(exc)
            if "Out of capacity" in msg or exc.status in (429, 500):
                print(f"Hết chỗ (Out of capacity). Sẽ thử lại sau {delay_seconds}s...")
            else:
                print(f"Mã lỗi {exc.status} ({exc.code}): {msg[:120]}...")
        except Exception as e:
            print(f"Lỗi mạng tạm thời: {e}. Thử lại...")

        time.sleep(delay_seconds)

if __name__ == "__main__":
    launch_hunter()

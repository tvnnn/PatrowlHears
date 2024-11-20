#!/bin/bash

PATROWLHEARSDATA_REPO="https://github.com/Patrowl/PatrowlHearsData"

lastrelease() { git ls-remote --tags "$1" | cut -d/ -f3- | tail -n1; }

# Create a temporary directory
tmp_dir=$(mktemp -d -t ci-XXXXXXXXXX)
echo "Using tmp dir: $tmp_dir"

echo "[+] Download and untar the latest release of PatrowlHearsData"
last_release=$(lastrelease $PATROWLHEARSDATA_REPO)
wget -P $tmp_dir $PATROWLHEARSDATA_REPO/archive/${last_release}.tar.gz

echo "[+] Untar archive"
tar -xzf $tmp_dir/${last_release}.tar.gz -C $tmp_dir

# Catch the right extracted directory
data_dir=$(ls $tmp_dir | grep PatrowlHearsData)

# Function to calculate checksum
calculate_checksum() {
    local file_path="$1"
    sha256sum "$file_path" | awk '{print $1}'
}

# Function to import with individual checksum check
import_with_checksum() {
    local data_file="$1"
    local checksum_file="$2"
    local import_command="$3"

    if [ -f "$data_file" ]; then
        new_checksum=$(calculate_checksum "$data_file")
        if [ -f "$checksum_file" ]; then
            old_checksum=$(cat "$checksum_file")
        fi

        if [ "$new_checksum" != "$old_checksum" ]; then
            echo "[+] Importing $(basename "$data_file")"
            eval "$import_command"
            echo "$new_checksum" > "$checksum_file"
        else
            echo "[i] No changes in $(basename "$data_file"), skipping import."
        fi
    else
        echo "[!] Data file $data_file not found, skipping."
    fi
}

lastupdate=""
[ -f var/data/lastupdate.txt ] && lastupdate="-l $(cat var/data/lastupdate.txt)"
echo "[i] Last update: $lastupdate"

# Paths for checksum files
mkdir -p var/data/checksums
cwes_checksum_file="var/data/checksums/cwes-diff-checksum.txt"
cpes_checksum_file="var/data/checksums/cpes-diff-checksum.txt"
cves_checksum_file="var/data/checksums/cves-diff-checksum.txt"
vias_checksum_file="var/data/checksums/vias-diff-checksum.txt"

echo "[+] Import data (diff from base)"
import_with_checksum "${tmp_dir}/${data_dir}/CWE/data/cwes-diff.json" "$cwes_checksum_file" "/root/.pyenv/versions/3.9.20/bin/python manage.py importcwes -i ${tmp_dir}/${data_dir}/CWE/data/cwes-diff.json"
/root/.pyenv/versions/3.9.20/bin/python manage.py importcpes -i ${tmp_dir}/${data_dir}/CPE/data/cpes-diff.json
/root/.pyenv/versions/3.9.20/bin/python manage.py importcves -d ${tmp_dir}/${data_dir}/CVE/data/ $lastupdate
import_with_checksum "${tmp_dir}/${data_dir}/VIA/data/via-diff.json" "$vias_checksum_file" "/root/.pyenv/versions/3.9.20/bin/python manage.py importvias -i ${tmp_dir}/${data_dir}/VIA/data/via-diff.json"

echo "[+] Remove tmp dir"
rm -rf $tmp_dir

current_date=$(/root/.pyenv/versions/3.9.20/bin/python -c 'from datetime import datetime as dt; print(dt.today().strftime("%Y-%m-%d"))')
echo $current_date > var/data/lastupdate.txt

#!/bin/bash

echo "=== Phison NVMe Controller PCIe Link Status Check with NVMe Mapping ==="

phison_pcis=$(lspci | grep -i phison | awk '{print $1}')

if [ -z "$phison_pcis" ]; then
    echo "No Phison controllers found"
    exit 1
fi

echo "Found Phison controllers at PCI addresses:"
echo "$phison_pcis"
echo

downgraded=0
total=0

# Create mapping table header
echo "| PCI Address | NVMe Device | Speed  | Width | Status    |"
echo "|-------------|-------------|--------|-------|-----------|"
echo

# Function to map PCI address to NVMe device
get_nvme_dev() {
    local pci=$1
    # Check /sys/class/nvme for PCI mapping
    for nvme_dir in /sys/class/nvme/nvme*; do
        if [ -d "$nvme_dir" ]; then
            pci_link=$(readlink "$nvme_dir/address" 2>/dev/null)
            if echo "$pci_link" | grep -q "$pci"; then
                basename "$(readlink "$nvme_dir")" | sed 's/nvme//; s/p[0-9]*$/n1/'
                return
            fi
        fi
    done
    
    # Fallback: check lsblk for nvme devices and match by order
    local count=0
    for dev in $(lsblk -o NAME,TYPE | grep disk | grep nvme | awk '{print $1}'); do
        if [ $count -eq $(echo "$phison_pcis" | grep -n "^$pci$" | cut -d: -f1) ]; then
            echo "nvme${count}n1"
            return
        fi
        ((count++))
    done
    
    echo "Not mapped"
}

for pci in $phison_pcis; do
    echo "Checking $pci..."
    
    # Get full LnkSta line
    lnk_line=$(lspci -s "$pci" -vv | grep -i lnksta | head -1)
    echo "  $lnk_line"
    
    # Extract Width and Speed
    width=$(echo "$lnk_line" | grep -o 'Width x[0-4]' | grep -o '[0-4]' | head -1)
    speed=$(echo "$lnk_line" | grep -o '[0-9]\+GT/s' | grep -o '[0-9]\+' | head -1)
    
    # Get NVMe device mapping
    nvme_dev=$(get_nvme_dev "$pci")
    
    status="OK"
    if [ "$speed" = "32" ] && [ "$width" != "4" ]; then
        status="DOWNGRADED"
        ((downgraded++))
    elif [ "$speed" = "16" ] && [ "$width" != "4" ]; then
        status="DOWNGRADED"
        ((downgraded++))
    fi
    
    ((total++))
    
    # Print table row
    printf "| %-11s | %-11s | %-5s  | x%-3s | %-9s |\n" "$pci" "$nvme_dev" "${speed}GT/s" "$width" "$status"
    echo
done

echo "=== SUMMARY ==="
echo "Total Phison controllers: $total"
echo "Downgraded links: $downgraded"
echo "Full x4 links: $((total - downgraded))"

if [ $downgraded -gt 0 ]; then
    echo "⚠️  WARNING: $downgraded PCIe link(s) NOT at full x4 width"
    echo "Check physical slots for nvme devices showing DOWNGRADED"
    exit 1
else
    echo "✅ All Phison controllers at full x4 width"
    exit 0
fi

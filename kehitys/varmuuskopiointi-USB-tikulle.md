# Varmuuskopiointi USB-tikulle

Heinäautomaatin konfiguraatiot kannattaa varmistaa esim. USB-tikulle.
Kopioinnilla voi varmistaa skriptit ja niiden asetukset, mutta jos koko RPi pitää asentaa uusiksi (esim. SD-kortti hajoaa) joutuu käyttöjärjestelmän ja python sekä pip -kirjastot kuitenkin asentamaan uudelleen. Omat asetukset sen sijaan on helppo palauttaa USB-tikulta.

## Miten löydän USB-tikun?
Kun kytket USB-tikun RPi:n USB-porttiin, hankaluutena on usein löytää kyseinen laite ja ottaa se käyttöön.
Yksi tapa on käyttää komentoa dmesg tikun heti tikun kytkemisen jälkeen.

---
```bash
sudo dmesg

[14253.783615] usb 1-1.2: new high-speed USB device number 6 using dwc_otg
[14253.874783] usb 1-1.2: New USB device found, idVendor=1307, idProduct=0163, bcdDevice= 1.00
[14253.874824] usb 1-1.2: New USB device strings: Mfr=1, Product=2, SerialNumber=3
[14253.874842] usb 1-1.2: Product: USB Mass Storage Device
[14253.874857] usb 1-1.2: Manufacturer: P Technology
[14253.874871] usb 1-1.2: SerialNumber: 000000000003F6
[14253.876027] usb-storage 1-1.2:1.0: USB Mass Storage device detected
[14253.877199] scsi host0: usb-storage 1-1.2:1.0
[14254.896702] scsi 0:0:0:0: Direct-Access     UT163    USB Flash Disk   0.00 PQ: 0 ANSI: 2
[14254.928745] sd 0:0:0:0: Attached scsi generic sg0 type 0
[14255.008910] sd 0:0:0:0: [sda] 1974271 512-byte logical blocks: (1.01 GB/964 MiB)
[14255.009741] sd 0:0:0:0: [sda] Write Protect is off
[14255.009752] sd 0:0:0:0: [sda] Mode Sense: 00 00 00 00
[14255.010421] sd 0:0:0:0: [sda] Asking for cache data failed
[14255.010429] sd 0:0:0:0: [sda] Assuming drive cache: write through
[14255.148723]  sda:
[14255.148864] sd 0:0:0:0: [sda] Attached SCSI removable disk
```
Tulosteesta nähdään, että laite esiintyy nimellä **sda** (käytännössä /dev/sda)
Katso myös
```bash
lsusb
Bus 001 Device 006: ID 1307:0163 Transcend Information, Inc. 256MB/512MB/1GB Flash Drive
```
Laite näkyy, mutta ilman varsinaista /dev nimeä.

## Laitteen käyttöönotto, osiot ja formatointi
Laitteen löydyttyä, sitä voi kutsua laitenimellä. Käytä esim. fdisk-ohjelmaa tikun osioiden selvittämiseen, vanhojen poistoon ja uusien muodostamiseen.


### Tikulla olevien osioiden listaus
```bash
sudo fdisk -l /dev/sda
Disk /dev/sda: 964 MiB, 1010826752 bytes, 1974271 sectors
Disk model: USB Flash Disk
Units: sectors of 1 * 512 = 512 bytes
Sector size (logical/physical): 512 bytes / 512 bytes
I/O size (minimum/optimal): 512 bytes / 512 bytes
Disklabel type: dos
Disk identifier: 0xc9d0c9d0

Device     Boot      Start        End    Sectors   Size Id Type
/dev/sda1         28886110  638537311  609651202 290.7G c4 DRDOS/sec (FAT-16 < 32M)
/dev/sda2       1183556331 4412578037 3229021707   1.5T 30 unknown
/dev/sda3       1325451862 2509223114 1183771253 564.5G 46 unknown
/dev/sda4       1394614348 1394635684      21337  10.4M 45 unknown

```

Esimerkkitikulla on peräti 4 osiota: sda1, sda2, sda3, sda4
Osioiden koot eivät kuitenkaan pidä paikkaansa. 


### Vanhojen osioiden poistoo

Tikku on käytetty, joten poistetaan kaikki vanhat osiot:

```bash
sudo fdisk /dev/sda

Command (m for help): m                      # m-kirjaimella ohje

Help:

  DOS (MBR)
   a   toggle a bootable flag
   b   edit nested BSD disklabel
   c   toggle the dos compatibility flag

  Generic
   d   delete a partition                     # käytä tätä
   F   list free unpartitioned space
   l   list known partition types
   n   add a new partition
   p   print the partition table
   t   change a partition type
   v   verify the partition table
   i   print information about a partition
   e   resize a partition
   T   discard (trim) sectors

Command (m for help): d                      # Poistetaan osio /dec/sda4
Partition number (1-4, default 4):

Partition 4 has been deleted.

Command (m for help): d                      # Poistetaan osio /dec/sda3
Partition number (1-3, default 3):

Partition 3 has been deleted.

Command (m for help): d                      # Poistetaan osio /dec/sda2
Partition number (1,2, default 2):

Partition 2 has been deleted.

Command (m for help): d                      # Poistetaan osio /dec/sda1
Selected partition 1
Partition 1 has been deleted.

Command (m for help):


Command (m for help): w                     # Kirjoitetaan muutokset tikulle

The partition table has been altered.
Calling ioctl() to re-read partition table.
Syncing disks.
```

Osiot saatiin poistettua (d) ja kirjoitettua muutokset tikulle (w).
Listauksessa ei enää näy yhtään osiota tikulla:

```bash
sudo fdisk -l /dev/sda
Disk /dev/sda: 964 MiB, 1010826752 bytes, 1974271 sectors
Disk model: USB Flash Disk
Units: sectors of 1 * 512 = 512 bytes
Sector size (logical/physical): 512 bytes / 512 bytes
I/O size (minimum/optimal): 512 bytes / 512 bytes
Disklabel type: dos
Disk identifier: 0xc9d0c9d0
```

### Uuden osion luonti

fdisk:ssä anna komennot järjestyksessä:

n — uusi osio
p — primary
1 — osionumero
Enter — oletusaloitussektori
Enter — oletuslopetussektori (koko tikku)
w — tallenna ja poistu

```bash
sudo fdisk /dev/sda

Welcome to fdisk (util-linux 2.41.5).
Changes will remain in memory only, until you decide to write them.
Be careful before using the write command.

The device contains 'vfat' signature and it will be removed by a write command. See fdisk(8) man page and --wipe option for more details.

Command (m for help): n
Partition type
   p   primary (0 primary, 0 extended, 4 free)
   e   extended (container for logical partitions)
Select (default p): p
Partition number (1-4, default 1): 1
First sector (2048-1974270, default 2048):
Last sector, +/-sectors or +/-size{K,M,G,T,P} (2048-1974270, default 1974270):

Created a new partition 1 of type 'Linux' and of size 963 MiB.

Command (m for help): w
The partition table has been altered.
Calling ioctl() to re-read partition table.
Syncing disks.


### Tikun formatointi linuxin ext4 formaattiin

Käytä komentoa ```bash sudo mkfs.ext4 -L backup /dev/sda1 ```
-L backup asettaa tikun nimeksi “backup” — kätevä tunnistamiseen

```bash
mke2fs 1.47.2 (1-Jan-2025)
Creating filesystem with 246527 4k blocks and 61696 inodes
Filesystem UUID: a5e0aca4-cb27-4a0c-be04-284bff3c59ca
Superblock backups stored on blocks:
        32768, 98304, 163840, 229376

Allocating group tables: done
Writing inode tables: done
Creating journal (4096 blocks): done
Writing superblocks and filesystem accounting information: done
```

### Hakemiston luonti ja osoittaminen tikulle
```bash
sudo mkdir /backup
sudo mount /dev/sda1 /backup
df -h
Filesystem      Size  Used Avail Use% Mounted on
...
/dev/sda1       930M  264K  866M   1% /backup
```
Tässä tapauksessa kyseessä on n. 1 gigan tikku ja siihen osoittaa hakemisto /backup.
Nyt tikku on valmis ja mountattu, mutta bootin jälkeen mounttaus ei ole enää voimassa.
Kätevintä on kirjoittaa mount-osoitus suoraan /etc/fstab tiedostoon

### Mounttaus automaattiseksi /etc/fstab kautta
Tikulla on aina yksilöllinen UUID ja se on luotettavin tapa tunnistaa tikku /etc/fstabissa — se ei muutu vaikka tikku kytkettäisiin eri USB-porttiin.

```bash
sudo blkid
/dev/sda1: LABEL="backup" UUID="a5e0aca4-cb27-4a0c-be04-284bff3c59ca" BLOCK_SIZE="4096" TYPE="ext4"
```bash

Sitten siirrytään muokkaamaan /etc/fstab -tiedostoa
```bash
sudo nano /etc/fstab
```
Lisää tiedoston loppuun rivi:
```bash
UUID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx  /backup  ext4  defaults,noatime  0  0
```
Korvaa UUID omalla arvollasi!


## Varmuuskopioinnin skriptit

Luo shelliskripti ```bash nano /home/pi/backup-files.sh ```, jossa on esim. seurava sisältö:


```bash

  1 #!/usr/bin/bash
  2 # ------------------------------------------------------------
  3 # Varmuuskopioidaan kotihakemisto ja /etc kohteeseen /backup
  4 # ------------------------------------------------------------
  5 rsync -rtqpog --delete /etc /backup/
  6 rsync -rtqpog --delete /home/pi /backup/
```

Rsync vivut:
-r rekusiivisesti (myös alihakemistot)
-t säilytä muokkausajat
-q hiljaisesti (tukahduttaa virheviestit)
-p säilytä oikeudet
-og säilyttää omistajuustiedot joka on kätevää palautustilanteessa
--delete on tärkeä — se poistaa backupista tiedostot jotka on poistettu lähteestä, jolloin backup pysyy siistinä eikä täytä tikkua vanhoilla tiedostoilla

Anna skriptille suoritusoikeudet
```bash chmod 755 /home/pi/backup-files.sh ```
ja lopuksi testaa toiminta

```bash
sudo /home/pi/backup-files.sh
ls /backup
```
Kohdekansioon /backup olisi pitänyt ilmestyä mm. kotihakemistosi sekä /etc hakemisto alihakemistoineen.

## Skriptin ajaminen ajastetusti
Skripti kannattaa ajaa esim. kerran vuorokaudessa automaattisesti.
Tämä tapahtuu crontab ajastuksella ja yhden käyttäjän RPi-laitteessa se on yksinkertaisinta laittaa yleiseen /etc/crontab -tiedostoon.

Lisää skripti esim. seuraavasti:
```bash
sudo nano /etc/crontab
```
Lisää loppuun rivi joka ajaa varmuuskopion esim. joka yö klo 03:00:

```bash
### Yöllinen backup /etc ja /home/pi/ -hakemistoista
0 3 * * *      root    /home/pi/backup-files.sh
```
Rsync kopioi vain muuttuneet tiedostot joten se on nopea ja tehokas. 
Toimii hyvin USB-tikulle.
Kun varmuuskopio tehdään pääkäyttäjän oikeuksilla, sillä on oikeus kopioida myös /etc -hakemisto
(...jossa on mm. muokkaamasi systemctl käynnistystiedostot.)


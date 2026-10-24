#!/usr/bin/bash
# ------------------------------------------------------------
# Varmuuskopioidaan kotihakemisto ja /etc kohteeseen /backup
# ------------------------------------------------------------
rsync -rtqpog --delete /etc /backup/
rsync -rtqpog --delete /home/labman /backup/



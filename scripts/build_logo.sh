conda activate anim_dev
# echo "$0"

SCRIPT=$(realpath "$0")
SCRIPTPATH=$(dirname "$SCRIPT")
# echo $SCRIPT
# echo $SCRIPTPATH
GIFFILE=$SCRIPTPATH/../doc/source/_static/logo_low.gif

if [ ! -f $GIFFILE ]; then
        echo "File not found!"

    anim $SCRIPTPATH/script.py  --folder $SCRIPTPATH/tmp

    ffmpeg -loglevel quiet -framerate 50 -f image2  \
        -i $SCRIPTPATH/tmp/imgs/img_%03d.png  \
        -filter_complex "[0:v] split [a][b]; [a] palettegen=reserve_transparent=on:transparency_color=000000 [p];[b][p] paletteuse" \
        -gifflags +transdiff -loop 0 $GIFFILE  -y
fi

# rm -rf $SCRIPTPATH/tmp

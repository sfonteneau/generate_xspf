import glob
import os
from urllib.parse import quote  
from jinja2 import Template

url_dl = r"https://nextcloud.mydomain.lan/s/123456/download"
folder='/downloads'
nextcloud_mode = True

list_ok=["3g2", "3gp", "3gp2", "3gpp", "amv", "asf", "avi", "bik", "crf", "dav", "divx", "drc", "dv", "dvr-ms" ,"evo", "f4v", "flv", "gvi", "gxf", "iso","m1v", "m2v", "m2t", "m2ts", "m4v", "mkv", "mov","mp2", "mp2v", "mp4", "mp4v", "mpe", "mpeg", "mpeg1", "mpeg2", "mpeg4", "mpg", "mpv2", "mts", "mtv", "mxf", "mxg", "nsv", "nuv","ogg", "ogm", "ogv", "ogx", "ps", "rec", "rm", "rmvb", "rpl", "thp", "tod", "ts", "tts", "txd", "vob", "vro", "webm", "wm", "wmv", "wtv", "xesc"]

template = r"""<?xml version="1.0" encoding="UTF-8"?>
<playlist xmlns="http://xspf.org/ns/0/" xmlns:vlc="http://www.videolan.org/vlc/playlist/ns/0/" version="1">
        <title>Liste de lecture</title>
        <trackList>
                {% for entry in dict_filename %}
                <track>
                        <title>{{ dict_filename[entry]['title']  }}</title>
                        <location>{{ dict_filename[entry]['urldl'] }}</location>
                        <extension application="http://www.videolan.org/vlc/playlist/0">
                                <vlc:id>{{dict_filename[entry]['nb']}}</vlc:id>
                                <vlc:option>network-caching=2000</vlc:option>
                        </extension>
                </track>{% endfor %}
        </trackList>
        <extension application="http://www.videolan.org/vlc/playlist/0">
                {% for entry in dict_filename %}
                <vlc:item tid="{{dict_filename[entry]['nb']}}"/>{% endfor %}
        </extension>
</playlist>
""" 

dict_filename = {}
nb = 0
for f in sorted(glob.glob('%s/**' % folder,recursive=True), key=os.path.getmtime,reverse=True):

    if os.path.isdir(f):
        continue
    if not f.split('.')[-1].lower() in list_ok:
        continue

    d = f[len(folder):]

    if len(d.split('/')) > 1:
        filename = d.rsplit('/')[-1]
        path = '/' + d.rsplit('/',1)[0]
    else:
        filename = d
        path= '/'
 
    title = filename.rsplit('.',1)[0].replace('.',' ').replace('_',' ')

    if not nextcloud_mode :
        dict_filename[title]= {"title":title,"urldl":url_dl + quote(d),"nb":str(nb)}
    else:
        if len(d.split('/')) > 1:
            filename = d.rsplit('/')[-1]
            path = '/' + d.rsplit('/',1)[0]
        else:
            filename = d
            path= '/'
        urldl = r"""%s?path=%s&amp;files=%s""" % (url_dl,quote(path),quote(filename))
        dict_filename[title]= {"title":title,"urldl":urldl,"nb":str(nb)}

    nb = nb + 1

ftest = Template(template)
datafinal = ftest.render(dict_filename=dict_filename)

with open('%s/vlc.xspf' % folder,"w") as f:
    f.write(datafinal)

# -*- coding: UTF-8 -*-
"""
CHM View Kit - chm viewer based on gtk webkit libraries

Copyright © 2011, Muayyad Alsadi <alsadi@ojuba.org>

    Released under terms of Waqf Public License.
    This program is free software; you can redistribute it and/or modify
    it under the terms of the latest version Waqf Public License as
    published by Ojuba.org.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

    The Latest version of the license can be found on
    "http://waqf.ojuba.org/license"

"""
import sys, os, os.path, time, re, sqlite3, hashlib

import shutil, tempfile
import threading, socket
import gettext
import gobject
import glib, gtk, pango
import webkit

from subprocess import Popen, PIPE
from urllib import unquote
from urlparse import urlparse, urlsplit

from paste import httpserver
from chm import chm

def async_gtk_call(f):
    def worker((function, args, kwargs)):
        function(*args, **kwargs)
    def f2(*args, **kwargs):
        gobject.idle_add(worker, (f, args, kwargs))
    return f2

setsid = getattr(os, 'setsid', None)
if not setsid: setsid = getattr(os, 'setpgrp', None)
_ps=[]

def run_in_bg(cmd):
  global _ps
  setsid = getattr(os, 'setsid', None)
  if not setsid: setsid = getattr(os, 'setpgrp', None)
  _ps=filter(lambda x: x.poll()!=None,_ps) # remove terminated processes from _ps list
  _ps.append(Popen(cmd,0,'/bin/sh',shell=True, preexec_fn=setsid))


def get_exec_full_path(fn):
  a=filter(lambda p: os.access(p, os.X_OK), map(lambda p: os.path.join(p, fn), os.environ['PATH'].split(os.pathsep)))
  if a: return a[0]
  return None


def guess_browser():
  e=get_exec_full_path("xdg-open")
  if not e: e=get_exec_full_path("firefox")
  if not e: e="start"
  return e

broswer=guess_browser()

def sure(msg, w=None):
  dlg=gtk.MessageDialog(w, gtk.DIALOG_MODAL,gtk.MESSAGE_QUESTION, gtk.BUTTONS_YES_NO, msg)
  dlg.connect("response", lambda *args: dlg.hide())
  r=dlg.run()
  dlg.destroy()
  return r==gtk.RESPONSE_YES


class WV(webkit.WebView):
  def __init__(self, key):
    webkit.WebView.__init__(self)
    self.key=key
    self.links_prompt=True
    self.set_full_content_zoom(True)
    self.connect_after("populate-popup", self.populate_popup)
    self.connect("navigation-requested", self._navigation_requested_cb)
    #self.connect("navigation-policy-decision-requested", self._navigation_policy_cb)

  def _navigation_policy_cb(self, view, frame, networkRequest, action, policy, *a, **kw):
    uri=networkRequest.get_uri()
    u=urlparse(uri)
    if u.scheme!='file' and u.hostname!='127.0.0.1' and u.hostname!='localhost':
      policy.ignore()
      if view.links_prompt and not sure(_("open [%s] in external browser") % uri, None): return True
      run_in_bg("%s '%s'" % (broswer ,uri))
      return True
    return False

  def _navigation_requested_cb(self, view, frame, networkRequest):
    uri=networkRequest.get_uri()
    u=urlparse(uri)
    if u.scheme!='file' and u.hostname!='127.0.0.1' and u.hostname!='localhost':
      if view.links_prompt and not sure(_("open [%s] in external browser") % uri, None): return 1
      run_in_bg("%s '%s'" % (broswer ,uri))
      return 1
    return 0


  def populate_popup(self, view, menu):
    menu.append(gtk.SeparatorMenuItem())
    i = gtk.ImageMenuItem(gtk.STOCK_ZOOM_IN)
    i.connect('activate', lambda m,v,*a,**k: v.zoom_in(), view)
    menu.append(i)
    i = gtk.ImageMenuItem(gtk.STOCK_ZOOM_OUT)
    i.connect('activate', lambda m,v,**k: v.zoom_out(), view)
    menu.append(i)
    i = gtk.ImageMenuItem(gtk.STOCK_ZOOM_100)
    i.connect('activate', lambda m,v,*a,**k: v.get_zoom_level() == 1.0 or v.set_zoom_level(1.0), view)
    menu.append(i)

    menu.show_all()
    return False

class TabLabel (gtk.HBox):
    """A class for Tab labels"""

    __gsignals__ = {
        "close": (gobject.SIGNAL_RUN_FIRST,
                  gobject.TYPE_NONE,
                  (gobject.TYPE_OBJECT,))
        }

    def __init__ (self, title, child):
        """initialize the tab label"""
        gtk.HBox.__init__(self, False, 4)
        self.title = title
        self.child = child
        self.label = gtk.Label(title)
        self.label.props.max_width_chars = 30
        self.label.set_ellipsize(pango.ELLIPSIZE_MIDDLE)
        self.label.set_alignment(0.0, 0.5)
        # FIXME: use another icon
        icon = gtk.image_new_from_icon_name("chmviewkit", gtk.ICON_SIZE_MENU)
        close_image = gtk.image_new_from_stock(gtk.STOCK_CLOSE, gtk.ICON_SIZE_MENU)
        close_button = gtk.Button()
        close_button.set_relief(gtk.RELIEF_NONE)
        close_button.connect("clicked", self._close_tab, child)
        close_button.add(close_image)
        self.pack_start(icon, False, False, 0)
        self.pack_start(self.label, True, True, 0)
        self.pack_start(close_button, False, False, 0)

        self.set_data("label", self.label)
        self.set_data("close-button", close_button)
        self.connect("style-set", tab_label_style_set_cb)

    def set_label_text (self, text):
        """sets the text of this label"""
        if text: self.label.set_label(text)

    def _close_tab (self, widget, child):
        self.emit("close", child)

def tab_label_style_set_cb (tab_label, style):
    context = tab_label.get_pango_context()
    metrics = context.get_metrics(tab_label.style.font_desc, context.get_language())
    char_width = metrics.get_approximate_digit_width()
    (width, height) = gtk.icon_size_lookup_for_settings(tab_label.get_settings(), gtk.ICON_SIZE_MENU)
    tab_label.set_size_request(20 * pango.PIXELS(char_width) + 2 * width, -1)
    button = tab_label.get_data("close-button")
    button.set_size_request(width + 4, height + 4)

class ContentPane (gtk.HPaned):
    __gsignals__ = {
        "focus-view-title-changed": (gobject.SIGNAL_RUN_FIRST,
                                     gobject.TYPE_NONE,
                                     (gobject.TYPE_OBJECT, gobject.TYPE_STRING,)),
        "focus-view-load-committed": (gobject.SIGNAL_RUN_FIRST,
                                      gobject.TYPE_NONE,
                                      (gobject.TYPE_OBJECT, gobject.TYPE_OBJECT,)),
        "new-window-requested": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE,
                                 (gobject.TYPE_OBJECT,))
        }

    def __init__ (self, win, default_url=None, default_title=None, hp=gtk.POLICY_NEVER, vp=gtk.POLICY_ALWAYS):
        """initialize the content pane"""
        gtk.HPaned.__init__(self)
        self.win=win
        self.tabs=gtk.Notebook()
        self.sidepane=gtk.Notebook()
        self.add1(self.sidepane)
        self.add2(self.tabs)
        self.sidepane.set_show_tabs(False)
        self.tabs.set_scrollable(True)
        self.default_url=default_url
        self.default_title=default_title
        self.hp=hp
        self.vp=vp
        self.tabs.props.scrollable = True
        self.tabs.props.homogeneous = True
        self.tabs.connect("switch-page", self._switch_page)

        self.show_all()
        self._hovered_uri = None

    def load (self, uri):
        """load the given uri in the current web view"""
        child = self.tabs.get_nth_page(self.tabs.get_current_page())
        wv = child.get_child()
        wv.open(uri)

    def new_tab_with_webview (self, webview):
        """creates a new tab with the given webview as its child"""
        self.tabs._construct_tab_view(webview)

    def new_tab (self, url=None, key=None):
        """creates a new page in a new tab"""
        # create the tab content
        wv = WV(key)
        #if url: wv.open(url)
        self._construct_tab_view(wv, url)
        return wv

    def _construct_tab_view (self, wv, url=None, title=None):
        wv.connect("hovering-over-link", self._hovering_over_link_cb)
        wv.connect("populate-popup", self._populate_page_popup_cb)
        wv.connect("load-committed", self._view_load_committed_cb)
        wv.connect("load-finished", self._view_load_finished_cb)
        wv.connect("create-web-view", self._new_web_view_request_cb)

        # load the content
        self._hovered_uri = None
        if not url: url=self.default_url
        else: wv.open(url)
        #elif url!=wv.get_property("uri"): wv.open(url)

        scrolled_window = gtk.ScrolledWindow()
        scrolled_window.props.hscrollbar_policy = self.hp
        scrolled_window.props.vscrollbar_policy = self.vp
        scrolled_window.add(wv)
        scrolled_window.show_all()

        # create the tab
        if not title: title=self.default_title
        if not title: title=url
        label = TabLabel(title, scrolled_window)
        label.connect("close", self._close_tab)
        label.show_all()

        new_tab_number = self.tabs.append_page(scrolled_window, label)
        self.tabs.set_tab_reorderable(scrolled_window, True)
        self.tabs.set_tab_label_packing(scrolled_window, False, False, gtk.PACK_START)
        self.tabs.set_tab_label(scrolled_window, label)

        # hide the tab if there's only one
        self.tabs.set_show_tabs(self.tabs.get_n_pages() > 1)

        self.show_all()
        self.tabs.set_current_page(new_tab_number)

    def _populate_page_popup_cb(self, view, menu):
        # misc
        if self._hovered_uri:
            open_in_new_tab = gtk.MenuItem(_("Open Link in New Tab"))
            open_in_new_tab.connect("activate", self._open_in_new_tab, view)
            menu.insert(open_in_new_tab, 0)
            menu.show_all()

    def _open_in_new_tab (self, menuitem, view):
        self.new_tab(self._hovered_uri, key=view.key)

    def _close_tab (self, label, child):
        page_num = self.tabs.page_num(child)
        if page_num != -1:
            view = child.get_child()
            view.destroy()
            self.tabs.remove_page(page_num)
        self.tabs.set_show_tabs(self.tabs.get_n_pages() > 1)

    def _switch_page (self, notebook, page, page_num):
        child = self.tabs.get_nth_page(page_num)
        view = child.get_child()
        frame = view.get_main_frame()
        self.emit("focus-view-load-committed", view, frame)
        key=view.key
        if key and self.win.app.chm[key].has_key("pane"):
          n=self.sidepane.page_num(self.win.app.chm[key]["pane"])
          if n>=0: self.sidepane.set_current_page(n)

    def _hovering_over_link_cb (self, view, title, uri):
        self._hovered_uri = uri


    def _view_load_committed_cb (self, view, frame):
        self.emit("focus-view-load-committed", view, frame)

    def _view_load_finished_cb(self, view, frame):
        child = self.tabs.get_nth_page(self.tabs.get_current_page())
        label = self.tabs.get_tab_label(child)
        title = frame.get_title()
        if not title:
           title = frame.get_uri()
        label.set_label_text(title)

    def _new_web_view_request_cb (self, web_view, web_frame):
        view=self.new_tab(key=web_view.key)
        view.connect("web-view-ready", self._new_web_view_ready_cb)
        return view

    def _new_web_view_ready_cb (self, web_view):
        self.emit("new-window-requested", web_view)

class BookSidePane(gtk.Notebook):
  def __init__(self, win, app, key):
    gtk.Notebook.__init__(self)
    self.win=win
    self.app=app
    self.key=key
    self.append_page(self.build_toc_tree(), gtk.Label(_('Topics Tree')))
    self.append_page(self.build_ix(), gtk.Label(_('Index')))
    self.append_page(gtk.Label("Search:"+key), gtk.Label(_('Search')))

  def build_ix(self):
    app,key=self.app,self.key
    s = gtk.TreeStore(str, str, bool, float) # label, url
    self.ix=gtk.TreeView(s)
    col=gtk.TreeViewColumn('Index', gtk.CellRendererText(), text=0)
    col.set_sizing(gtk.TREE_VIEW_COLUMN_AUTOSIZE)
    col.set_resizable(True)
    col.set_expand(True)
    self.ix.insert_column(col, -1)
    p=[None]
    l=[]
    for e in self.app.get_ix(key):
      while(l and l[-1]>=e['level']): p.pop(); l.pop()
      l.append(e['level'])
      p.append(s.append(p[-1],(e['name.utf8'], e.get('local', ''), e['is_page'], 1.0)))
    scroll=gtk.ScrolledWindow()
    scroll.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_ALWAYS)
    scroll.add(self.ix)
    self.ix.connect("cursor-changed", self._toc_cb)
    return scroll

  def build_toc_tree(self):
    app,key=self.app,self.key
    s = gtk.TreeStore(str, str, bool) # label, url
    self.tree=gtk.TreeView(s)
    col=gtk.TreeViewColumn('Topics', gtk.CellRendererText(), text=0)
    col.set_sizing(gtk.TREE_VIEW_COLUMN_AUTOSIZE)
    col.set_resizable(True)
    col.set_expand(True)
    self.tree.insert_column(col, -1)
    p=[None]
    l=[]
    for e in self.app.get_toc(key):
      while(l and l[-1]>=e['level']): p.pop(); l.pop()
      l.append(e['level'])
      p.append(s.append(p[-1],(e['name.utf8'], e.get('local', ''), e['is_page'])))
    scroll=gtk.ScrolledWindow()
    scroll.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_ALWAYS)
    scroll.add(self.tree)
    self.tree.connect("cursor-changed", self._toc_cb)
    return scroll

  def _toc_cb(self, tree, *a):
    s,i=tree.get_selection().get_selected()
    is_page=self.win.gen_url(self.key, s.get_value(i, 2))
    if is_page:
      url=self.win.gen_url(self.key, s.get_value(i, 1))
      self.win._content.load(url)

class MainWindow(gtk.Window):
  def __init__(self, app, port, server):
    self.app = app
    self.port = port
    self.server = server # we need this to quit the server when closing main window
    self._open_dlg=None
    
    gtk.window_set_default_icon_name('chmviewkit')
    gtk.Window.__init__(self)
    self.set_title(_('CHM View Kit'))
    self.set_default_size(600, 480)
    
    vb=gtk.VBox(False,0); self.add(vb)

    tools=gtk.Toolbar()
    vb.pack_start(tools, False, False, 2)
    
    self._content= ContentPane(self, None, _("CHM View Kit"))
    vb.pack_start(self._content,True, True, 2)

    b=gtk.ToolButton(gtk.STOCK_OPEN)
    b.connect('clicked', self._open_cb)
    b.set_tooltip_text(_("Open a CHM file"))
    tools.insert(b, -1)

    # TODO: add navigation buttons (back, forward ..etc.) and zoom buttons
    #tools.insert(gtk.SeparatorToolItem(), -1)

    img=gtk.Image()
    img.set_from_stock(gtk.STOCK_ZOOM_IN, gtk.ICON_SIZE_BUTTON)
    b=gtk.ToolButton(icon_widget=img, label=_("Zoom in"))
    b.set_is_important(True)
    b.set_tooltip_text("Makes things appear bigger")
    b.connect('clicked', lambda a: self._do_in_current_view("zoom_in"))
    tools.insert(b, -1)

    img=gtk.Image()
    img.set_from_stock(gtk.STOCK_ZOOM_OUT, gtk.ICON_SIZE_BUTTON)
    b=gtk.ToolButton(icon_widget=img, label=_("Zoom out"))
    b.set_tooltip_text("Makes things appear smaller")
    b.connect('clicked', lambda a: self._do_in_current_view("zoom_out"))
    tools.insert(b, -1)

    img=gtk.Image()
    img.set_from_stock(gtk.STOCK_ZOOM_100, gtk.ICON_SIZE_BUTTON)
    b=gtk.ToolButton(icon_widget=img, label=_("1:1 Zoom"))
    b.set_tooltip_text("restore original zoom factor")
    b.connect('clicked', lambda a: self._do_in_current_view("set_zoom_level",1.0))
    tools.insert(b, -1)

    tools.insert(gtk.SeparatorToolItem(), -1)

    #self._content.new_tab()

    self.connect("delete_event", self.quit)
    #self.drag_dest_set(gtk.DEST_DEFAULT_ALL,targets_l,(1<<5)-1)
    #self.connect('drag-data-received', self.drop_data_cb)
    
    self.show_all()

  def _show_open_dlg(self, *a):
    if self._open_dlg:
      return self._open_dlg.run()
    self._open_dlg=gtk.FileChooserDialog("Select files to import", buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT, gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
    ff=gtk.FileFilter()
    ff.set_name(_('CHM Files'))
    ff.add_mime_type('application/x-chm')
    self._open_dlg.add_filter(ff)
    ff=gtk.FileFilter()
    ff.set_name(_('All files'))
    ff.add_pattern('*')
    self._open_dlg.add_filter(ff)
    self._open_dlg.set_select_multiple(False)
    self._open_dlg.connect('delete-event', lambda w,*a: w.hide() or True)
    self._open_dlg.connect('response', lambda w,*a: w.hide() or True)
    return self._open_dlg.run()

  def gen_url(self, key, fn):
    return "http://127.0.0.1:%d/%s$/%s" % (self.port, key, fn)

  def _open_cb(self, *a):
    if self._show_open_dlg()!=gtk.RESPONSE_ACCEPT: return
    chmfn=self._open_dlg.get_filename()
    fn=""
    try:
      # FIXME: have a single method for this
      key=self.app.load_chm(chmfn)
      fn=self.app.get_toc(key)[0]['local']  # FIXME: just put cursor to first is_page
    except IOError: return # FIXME: show a nice error to user
    except KeyError: pass
    self._content.new_tab(self.gen_url(key, fn), key)
    pane=BookSidePane(self, self.app, key)
    self.app.chm[key]["pane"]=pane
    n=self._content.sidepane.append_page(pane)
    self._content.sidepane.get_nth_page(n).show_all()
    self._content.sidepane.set_current_page(n)
  
  def _do_in_current_view (self, action, *a, **kw):
     n = self._content.tabs.get_current_page()
     if n<0: return
     view=self._content.tabs.get_nth_page(n).get_child()
     getattr(view, action)(*a,**kw)

  def _do_in_all_views (self, action, *a, **kw):
     for n in range(self._content.tabs.get_n_pages()):
       view=self._content.tabs.get_nth_page(n).get_child()
       getattr(view, action)(*a,**kw)

  # TODO: add drag and drop support
  #def drop_data_cb(self, widget, dc, x, y, selection_data, info, t):
  #  if not self.import_w: self.import_w=ThImportWindow(self)
  #  for i in selection_data.get_uris():
  #    self.import_w.add_uri(i)
  #  self.import_w.show()
  #  dc.drop_finish (True, t);

  def quit(self,*args):
    self.server.running=False
    gtk.main_quit()
    return False

CHM_HIGH_PORT=18080

def launchServer(app):
  launched=False
  port=CHM_HIGH_PORT
  while(not launched):
    try: server=httpserver.serve(app, host='127.0.0.1', port=port, start_loop=False)
    except socket.error: port+=1
    else: launched=True
  return port, server

class ChmWebApp:
  _mimeByExtension={
    'html': 'text/html', 'htm': 'text/html', 'txt': 'text/plain',
    'css': 'text/css', 'js':'application/javascript',
    'ico': 'image/x-icon', 'png': 'image/png', 'gif': 'image/gif',
    'jpg': 'image/jpeg', 'jpeg': 'image/jpeg'
  }
  _li_re=re.compile(r'''(</?(?:ul|li)[^>]*>)''', re.I | re.S | re.M)
  _p_re=re.compile(r'''<param([^<>]+)>''', re.I | re.S | re.M)
  _kv_re=re.compile(r'''(\S+)\s*=\s*(["'])([^'"]*)\2''', re.I | re.S | re.M)
  _href_re=re.compile(r'''(<[^<>]+(?:href|src)=(["'])/)''', re.I | re.S | re.M)
  def __init__(self):
    self.key2file={}
    self.chm={}
    #self.chmf.LoadCHM('sayed-elkhater.chm')
    

  def __call__(self, environ, start_response):
    uri=environ['PATH_INFO']
    l=uri[1:].split('$/', 1) # we have the a key followed by $/ then the rest of the uri
    if len(l)==2:
      key,fn=l
      fn='/'+fn
    else:
      # in case of no key guess it from referrer
      ref=environ.get('HTTP_REFERER','')
      (scheme, netloc, path, query, fragment) = urlsplit(ref)
      if ref and '$' in path:
        l=path[1:].split('$', 1)
        key=l[0]
        fn=uri
        # we can continue without redirect, but it's better to redirect so that we always have a valid referrer
        start_response("302 moved", [('content-type', 'text/plain'), ('Location', "/"+key+"$"+fn)])
        return ("moved",)
      else:
        # in case of no key and no valid referrer give 404
        start_response("404 Not found", [('content-type', 'text/plain')])
        return ('not found',)

    ext=fn[fn.rfind('.'):][1:].lower()
    mime=self._mimeByExtension.get(ext,"application/octet-stream")
    chmf=self.get_chmf(key)
    s,u=chmf.ResolveObject(fn)
    if s!=0:
      start_response("404 Not found", [('content-type', 'text/plain')])
      return ('not found',)
    l,data=chmf.RetrieveObject(u)
    start_response("200 OK", [('content-type', mime)])
    # to test referrer fix comment out next line
    if ext=='htm': data=self._href_re.sub(r'\1'+key+'$/',data)
    return (data,)

  def load_chm(self, fn):
    key=hashlib.md5(fn).digest().encode('base64')[:-3].replace('/', '_').replace('+', '-')
    if self.key2file.has_key(key): return key
    self.key2file[key]=fn
    return key

  def get_chmf(self, key):
    if not self.chm.has_key(key):
      self.chm[key]={}
    if not self.chm[key].has_key('chmf'):
      fn=self.key2file[key]
      chmf=chm.CHMFile()
      s=chmf.LoadCHM(fn)
      if s!=1: raise IOError
      self.chm[key]['chmf']=chmf
    return self.chm[key]['chmf']

  def _parse_toc_html(self, html):
    li=self._li_re
    p=self._p_re
    level=0
    toc=[]
    for i in li.split(html):
      e={}
      ul=i.lower()
      if ul.startswith('<ul'): level+=1
      elif ul.startswith('</ul'): level-=1
      for m in p.findall(i):
        param={}
        for k,j2,v in self._kv_re.findall(m):
          param[k.lower().strip(" \t\n\r\"'")]=v.strip(" \t\n\r\"'")
        if param.has_key('name') and param.has_key('value'):
          e[param['name'].lower()]=param['value']
          try: u=param['value'].decode('utf-8')
          except UnicodeDecodeError: u=param['value'].decode('windows-1256')
          e[param['name'].lower()+'.utf8']=u
      e['level']=level
      e['is_page']=e.has_key('local')
      if e.has_key('name'): toc.append(e)
    return toc

  def get_toc(self, key):
    chmf=self.get_chmf(key)
    if self.chm[key].has_key('toc'): return self.chm[key]['toc']
    toc=self._parse_toc_html(chmf.GetTopicsTree())
    self.chm[key]['toc']=toc
    return toc

  def get_ix(self, key):
    chmf=self.get_chmf(key)
    if self.chm[key].has_key('ix'): return self.chm[key]['ix']
    ix=self._parse_toc_html(chmf.GetIndex())
    self.chm[key]['ix']=ix
    return ix


def main():
  exedir=os.path.dirname(sys.argv[0])
  ld=os.path.join(exedir,'..','share','locale')
  if not os.path.isdir(ld): ld=os.path.join(exedir, 'locale')
  gettext.install('chmviewkit', ld, unicode=0)

  app=ChmWebApp()
  port, server=launchServer(app)
  gobject.threads_init()
  threading.Thread(target=server.serve_forever, args=()).start()
  while(not server.running): time.sleep(0.25)
  gtk.gdk.threads_enter()
  w=MainWindow(app, port, server)
  gtk.main()
  gtk.gdk.threads_leave()

if __name__ == "__main__":
  main()


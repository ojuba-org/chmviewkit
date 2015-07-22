%global owner ojuba-org
%global commit #Write commit number here

Name: chmviewkit
Summary: Webkit/Gtk-based CHM viewer
Summary(ar): عارض ملفات CHM
URL: http://ojuba.org/
Version: 0.2.3
Release: 3%{?dist}
Source: https://github.com/%{owner}/%{name}/archive/%{commit}/%{name}-%{commit}.tar.gz
License: WAQFv2
BuildArch: noarch
Requires: python2
Requires: python-paste
Requires: python-chm
Requires: pygobject3 >= 3.0.2
BuildRequires: gettext
BuildRequires: intltool
BuildRequires: ImageMagick
BuildRequires: python2-devel

%description
Webkit/Gtk-based CHM viewer.

%description -l ar
عارض ملفات CHM متوافق مع ويبكيت و ج.ت.ك.

%prep
%setup -q -n %{name}-%{commit}

%build
make %{?_smp_mflags}

%install
%make_install

%post
touch --no-create %{_datadir}/icons/hicolor || :
if [ -x %{_bindir}/gtk-update-icon-cache ] ; then
%{_bindir}/gtk-update-icon-cache --quiet %{_datadir}/icons/hicolor || :
fi

%postun
touch --no-create %{_datadir}/icons/hicolor || :
if [ -x %{_bindir}/gtk-update-icon-cache ] ; then
%{_bindir}/gtk-update-icon-cache --quiet %{_datadir}/icons/hicolor || :
fi

%files
%license waqf2-ar.pdf
%doc README TODO AUTHORS
%{_bindir}/chmviewkit
%{python2_sitelib}/chmviewkit*
%{python2_sitelib}/*.egg-info
%{_datadir}/icons/hicolor/*/apps/*.png
%{_datadir}/icons/hicolor/*/apps/*.svg
%{_datadir}/applications/*.desktop
%{_datadir}/locale/*/*/*.mo

%changelog
* Wed Jul 22 2015 Mosaab Alzoubi <moceap@hotmail.com> - 0.2.3-3
- General Rivision
- Remove group tag
- Remove old ATTR way
- Use %%make_install and %%license
- Add Arabic summary and description
- Fix requires and BRs

* Tue Feb 18 2014 Mosaab Alzoubi <moceap@hotmail.com> - 0.2.3-2
- General Revision.

* Sat Jun 2 2012  Muayyad Saleh AlSadi <alsadi@ojuba.org> - 0.2.3-1
- port to gtk3, webkit3

* Fri Jan 13 2012  Muayyad Saleh AlSadi <alsadi@ojuba.org> - 0.2.2-1
- new release with recent support

* Sat Jul 2 2011  Muayyad Saleh AlSadi <alsadi@ojuba.org> - 0.2.0-1
- fully featured stable release

* Sun Jun 19 2011  Muayyad Saleh AlSadi <alsadi@ojuba.org> - 0.1.0-1
- initial packing

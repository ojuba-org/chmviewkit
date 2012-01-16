Name: chmviewkit
Summary: Webkit/Gtk-based CHM viewer
URL: http://www.ojuba.org/
Version: 0.2.2
Release: 1%{?dist}
Source0: http://git.ojuba.org/cgit/%{name}/snapshot/%{name}-%{version}.tar.bz2
License: Waqf
Group: System Environment/Base
BuildArch: noarch
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
Requires: python, python-paste, python-chm, pygtk2, pywebkitgtk
BuildRequires: gettext, intltool, ImageMagick
BuildRequires: python

%{!?python_sitelib: %global python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib(1)")}

%description
chmviewkit Webkit/Gtk-based CHM viewer

%prep
%setup -q
%build
make %{?_smp_mflags}

%install
rm -rf $RPM_BUILD_ROOT
%makeinstall DESTDIR=$RPM_BUILD_ROOT

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

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
%doc LICENSE-ar.txt LICENSE-en README TODO AUTHORS
%{_bindir}/chmviewkit
%{python_sitelib}/chmviewkit*
%{python_sitelib}/*.egg-info
%{_datadir}/icons/hicolor/*/apps/*.png
%{_datadir}/icons/hicolor/*/apps/*.svg
%{_datadir}/applications/*.desktop
%{_datadir}/locale/*/*/*.mo

%changelog
* Fri Jan 13 2012  Muayyad Saleh AlSadi <alsadi@ojuba.org> - 0.2.2-1
- new release with recent support

* Sat Jul 2 2011  Muayyad Saleh AlSadi <alsadi@ojuba.org> - 0.2.0-1
- fully featured stable release

* Sat Jun 19 2011  Muayyad Saleh AlSadi <alsadi@ojuba.org> - 0.1.0-1
- initial packing


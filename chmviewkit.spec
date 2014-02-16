%global owner ojuba-org
%global commit #Write commit number here

Name:		chmviewkit
Summary:	Webkit/Gtk-based CHM viewer
URL:		http://ojuba.org/
Version:	0.2.3
Release:	2%{?dist}
Source:		https://github.com/%{owner}/%{name}/archive/%{commit}/%{name}-%{commit}.tar.gz
License:	WAQFv2
Group:		System Environment/Base
BuildArch:	noarch
Requires:	python2
Requires:	python-paste
Requires:	python-chm
Requires:	pygobject3 >= 3.0.2
BuildRequires:	gettext
BuildRequires:	intltool
BuildRequires:	ImageMagick
BuildRequires:	python2
BuildRequires:	python2-devel

%description
chmviewkit Webkit/Gtk-based CHM viewer

%prep
%setup -q -n %{name}-%{commit}

%build
make %{?_smp_mflags}

%install
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

%files
%defattr(-,root,root,-)
%doc waqf2-ar.pdf README TODO AUTHORS
%{_bindir}/chmviewkit
%{python2_sitelib}/chmviewkit*
%{python2_sitelib}/*.egg-info
%{_datadir}/icons/hicolor/*/apps/*.png
%{_datadir}/icons/hicolor/*/apps/*.svg
%{_datadir}/applications/*.desktop
%{_datadir}/locale/*/*/*.mo

%changelog
* Sun Jun 2 2012 Mosaab Alzoubi <moceap@hotmail.com> - 0.2.3-2
- General Revision.

* Sun Jun 2 2012  Muayyad Saleh AlSadi <alsadi@ojuba.org> - 0.2.3-1
- port to gtk3, webkit3

* Fri Jan 13 2012  Muayyad Saleh AlSadi <alsadi@ojuba.org> - 0.2.2-1
- new release with recent support

* Sat Jul 2 2011  Muayyad Saleh AlSadi <alsadi@ojuba.org> - 0.2.0-1
- fully featured stable release

* Sat Jun 19 2011  Muayyad Saleh AlSadi <alsadi@ojuba.org> - 0.1.0-1
- initial packing

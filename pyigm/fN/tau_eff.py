""" Module for tau_eff calculations
"""
import pdb
import yaml
import imp

import numpy as np
from scipy import interpolate

from astropy import constants as const
from astropy import units as u
from astropy.cosmology import FlatLambdaCDM

from linetools.analysis import absline as ltaa
from linetools.lists.linelist import LineList

from pyigm.fN.fnmodel import FNModel
from pyigm import utils as pyigmu

pyigm_path = imp.find_module('pyigm')[1]

def lyman_limit(fN_model, z912, zem, N_eval=5000, cosmo=None, debug=False):
    """ Calculate teff_LL

    Effective opacity from LL absorption at z912 from zem

    Parameters
    ----------
    fN_model : FNModel
      f(N) model
    z912 : float
      Redshift for evaluation
    zem : float
      Redshift of source
    cosmo : astropy.cosmology, optional
      Cosmological model to adopt (as needed)
    N_eval : int, optional
      Discretization parameter (5000)
    debug : bool, optional

    Returns
    -------
    zval : array
    teff_LL : array
      z values and Effective opacity from LL absorption from z912 to zem
    """
    if not isinstance(fN_model,FNModel):
        raise IOError("Improper model")
    # NHI array
    lgNval = 11.5 + 10.5*np.arange(N_eval)/(N_eval-1.)  #; This is base 10 [Max at 22]
    dlgN = lgNval[1]-lgNval[0]
    Nval = 10.**lgNval

    # z array
    zval = z912 + (zem-z912)*np.arange(N_eval)/(N_eval-1.)
    dz = np.fabs(zval[1]-zval[0])

    teff_LL = np.zeros(N_eval)

    # dXdz
    dXdz = pyigmu.cosm_xz(zval, cosmo=cosmo, flg_return=1)

    # Evaluate f(N,X)
    velo = (zval-zem)/(1+zem) * (const.c.cgs.value/1e5)  # Kludge for eval [km/s]

    log_fnX = fN_model.evaluate(lgNval, zem, vel_array=velo)
    log_fnz = log_fnX + np.outer(np.ones(N_eval), np.log10(dXdz))

    # Evaluate tau(z,N)
    teff_engy = (const.Ryd.to(u.eV, equivalencies=u.spectral()) /
                 ((1+zval)/(1+zem)) )
    sigma_z = ltaa.photo_cross(1, 1, teff_engy)
    tau_zN = np.outer(Nval, sigma_z)

    # Integrand
    intg = 10.**(log_fnz) * (1. - np.exp(-1.*tau_zN))

    # Sum
    sumz_first = False
    if sumz_first == False:
        #; Sum in N first
        N_summed = np.sum(intg * np.outer(Nval, np.ones(N_eval)),  0) * dlgN * np.log(10.)
        # Sum in z
        teff_LL = (np.cumsum(N_summed[::-1]))[::-1] * dz

    # Debug
    if debug is True:
        pdb.set_trace()
    # Return
    return zval, teff_LL


def lyman_ew(ilambda, zem, fN_model, NHI_MIN=11.5, NHI_MAX=22.0, N_eval=5000,
                  EW_spline=None, bval=24., fNz=False, cosmo=None, debug=False,
                  cumul=None, verbose=False):
    """ tau effective from HI Lyman series absorption

    Parameters
    ----------
    ilambda : float
        Observed wavelength (Ang)
    zem : float
        Emission redshift of the source [sets which Lyman lines are included]
    bva : float
         -- Characteristics Doppler parameter for the Lya forest
         -- [Options: 24, 35 km/s]
    NHI_MIN : float
         -- Minimum log HI column for integration [default = 11.5]
    NHI_MAX : float
         -- Maximum log HI column for integration [default = 22.0]
    fNz : Boolean (False)
         -- Inputs f(N,z) instead of f(N,X)
    cosmo : astropy.cosmology (None)
         -- Cosmological model to adopt (as needed)
    cumul : List of cumulative sums
         -- Recorded only if cumul is not None

    Returns
    -------
    teff : float
      Total effective opacity of all lines contributing

    ToDo:
      1. Parallelize the Lyman loop
    """
    # Lambda
    if not isinstance(ilambda, float):
        raise ValueError('tau_eff: ilambda must be a float for now')
    Lambda = ilambda
    if not isinstance(Lambda,u.quantity.Quantity):
        Lambda = Lambda * u.AA # Ang

    # Read in EW spline (if needed)
    if EW_spline == None:
        if int(bval) == 24:
            EW_FIL = pyigm_path+'/data/fN/EW_SPLINE_b24.yml'
            with open(EW_FIL, 'r') as infile:
                EW_spline = yaml.load(infile)  # dict from mk_ew_lyman_spline
        else:
            raise ValueError('tau_eff: Not ready for this bvalue %g' % bval)

    # Lines
    HI = LineList('HI')
    wrest = HI._data['wrest']

    # Find the lines
    gd_Lyman = wrest[(Lambda/(1+zem)) < wrest]
    nlyman = len(gd_Lyman)
    if nlyman == 0:
        if verbose:
            print('igm.tau_eff: No Lyman lines covered at this wavelength')
        return 0

    # N_HI grid
    lgNval = NHI_MIN + (NHI_MAX-NHI_MIN)*np.arange(N_eval)/(N_eval-1) # Base 10
    dlgN = lgNval[1]-lgNval[0]
    Nval = 10.**lgNval
    teff_lyman = np.zeros(nlyman)

    # For cumulative
    if not cumul is None:
        cumul.append(lgNval)

    # Loop on the lines
    for qq, line in enumerate(gd_Lyman): # Would be great to do this in parallel...
                             # (Can pack together and should)
        # Redshift
        zeval = ((Lambda / line) - 1).value
        if zeval < 0.:
            teff_lyman[qq] = 0.
            continue
        # Cosmology
        if fNz is False:
            if cosmo not in locals():
                cosmo = FlatLambdaCDM(H0=70, Om0=0.3) # Vanilla
            #dxdz = (np.fabs(xigmu.cosm_xz(zeval-0.1, cosmo=cosmo)-
            #            xigmu.cosm_xz(zeval+0.1,cosmo=cosmo)) / 0.2 )
            #xdb.set_trace()
            dxdz = pyigmu.cosm_xz(zeval,cosmo=cosmo,flg_return=1)
        else: dxdz = 1. # Code is using f(N,z)

        # Get EW values (could pack these all together)
        idx = np.where(EW_spline['wrest']*u.AA == line)[0]
        if len(idx) != 1:
            raise ValueError('tau_eff: Line %g not included or over included?!' % line)
        restEW = interpolate.splev(lgNval, EW_spline['tck'][idx], der=0)

        # dz
        dz = ((restEW*u.AA) * (1+zeval) / line).value

        # Evaluate f(N,X) at zeval
        log_fnX = fN_model.evaluate(lgNval,zeval).flatten()

        # Sum
        intgrnd = 10.**(log_fnX) * dxdz * dz * Nval
        teff_lyman[qq] = np.sum(intgrnd) * dlgN * np.log(10.)
        if not cumul is None:
            cumul.append( np.cumsum(intgrnd) * dlgN * np.log(10.) )

        # Debug
        if debug:
            try:
                from xastropy.xutils import xdebug as xdb
            except ImportError:
                break
            xdb.xplot(lgNval, np.log10(10.**(log_fnX) * dxdz * dz * Nval))
            #x_splot, lgNval, total(10.d^(log_fnX) * dxdz * dz * Nval,/cumul) * dlgN * alog(10.) / teff_lyman[qq], /bloc
            #printcol, lgnval, log_fnx, dz,  alog10(10.d^(log_fnX) * dxdz * dz * Nval)
            #writecol, 'debug_file'+strtrim(qq,2)+'.dat',  lgNval, restEW, log_fnX
            xdb.set_trace()

    # Return
    return np.sum(teff_lyman)


def map_lymanew(dict_inp):
    """ Simple routine to enable parallel processing

    Parameters
    ----------
    dict_inp : dict
      dict containing the key info
    """
    teff = lyman_ew(dict_inp['ilambda'], dict_inp['zem'], dict_inp['fN_model'])
    # Return
    return teff


def lyman_alpha_obs(z):
    """Report an 'observed' teff value from one of these studies

      0 < z < 1.6:  Kirkman+07
      1.6 < z < 2.3:  Kirkman+05
      2.3 < z < 4.9:  Becker+13

    Parameters
    ----------
    z : float
      Redshift

    Returns
    -------
    teff : float
      Observed teff from HI Lya
    """
    # Low-z
    if z < 1.6:
        # D_A from Kirkman+07
        print('Calculating tau_eff from Kirkman+07')
        #  No LLS, no metals [masked]
        #  Unclear in the paper, but I think the range is log NHI = 12-16
        DA = 0.016 * (1+z)**1.01
        teff = -1. * np.log(1.-DA)
    elif (z >= 1.6) & (z < 2.3):
        # D_A from Kirkman+05
        print('Calculating tau_eff from Kirkman+05')
        #  No LLS, no metals [masked]
        DA = 0.0062 * (1+z)**2.75
        teff = -1. * np.log(1.-DA)
    elif (z >= 2.3) & (z < 4.9):
        # Becker+13
        print('Calculating tau_eff from Becker+13')
        tau0 = 0.751
        beta = 2.90
        C = -0.132
        z0 = 3.5
        teff = tau0 * ((1+z)/(1+z0))**beta + C
    else:
        raise ValueError('teff_obs: Not ready for z={:g}'.format(z))

    # Return
    return teff

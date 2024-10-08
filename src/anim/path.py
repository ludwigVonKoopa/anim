import logging

import numpy as np
import xarray as xr
from scipy import interpolate

logger = logging.getLogger(__name__)


class Path:
    """Generate camera path for the animation.

    You gives the initial pos (x0, y0) and the dx,dy.
    This gives the camera coordinate : [x0-dx, x0+dx, y0-dy, y0+dy]

    t0 can be either:
        * a date (a :class:`numpy.datetime64`)
        *


    Permet de générer le trajet de caméra pour les vidéos.

    On donne la position initiale (x0, y0), ainsi que dx, dy, ce qui donne
    les coordonnées de la caméra [x0-dx, x0+dx, y0-dy, y0+dy]

    t0 peut être une date (:class:`numpy.datetime64`), dans ce cas, chaque appel à :meth:`Path.add_deplacement`
    doit utiliser un np.datetime64 ou np.timedelta64 pour l'indice,

    Sinon on peut lui spécifier t0 = int, et dans ce cas l'indice utilisé dans :meth:`Path.add_deplacement` doit correspondre
    au nombre d'images à attendre


    Parameters
    ----------
    coords : tuple, optional
        position (x0, y0) au début du chemin, by default (180, 0)
    dx : int, optional
        demi taille horizontal de la caméra, by default 180
    dy : int, optional
        demi taille verticale de la caméra, by default 90
    t0 : numpy.datetime64, or int, optional
        Date au début du chemin. Peut être une date, ou un entier qui représente les images, by default 0

    Raises
    ------
    TypeError
        si t0 n'est pas int ou np.datetime64
    """

    def __init__(self, coords=(180, 0), dx=180, dy=90, t0=0):
        self._sanitize_coords(coords)
        self._times = [t0]
        self._coords = [coords]
        self._dxs = [dx]
        self._dys = [dy]

    @classmethod
    def _sanitize_coords(cls, coords):
        if coords is not None and len(coords) != 2:
            logger.error(f"coords shoud be None or a tuple(x,y), not {type(coords)}")
            raise TypeError("coords bad type")

    def move(self, time, coords=None):
        self.move_and_focus(time, None, None, coords)

    def move_and_zoom(self, time, zoom, coords=None):
        old_dx, old_dy = self._dxs[-1], self._dys[-1]
        self.move_and_focus(time, old_dx / zoom, old_dy / zoom, coords)

    def move_and_focus(self, time, dx=None, dy=None, coords=None):
        self._sanitize_time(time)
        self._sanitize_coords(coords)

        if coords is None:
            coords = self._coords[-1]

        if dx is None:
            dx = self._dxs[-1]
        if dy is None:
            dy = self._dys[-1]

        self._coords.append(coords)
        self._dxs.append(dx)
        self._dys.append(dy)
        self._add_time(time)

    def _merge_moves(self, dt):
        x, y = np.array(self._coords).T
        dates = np.array(self._times)
        dxs = np.array(self._dxs)
        dys = np.array(self._dys)
        time_coords = np.arange(dates[0], dates[-1], dt)
        return x, y, dxs, dys, dates, time_coords

    def _interp_moves(self, x, y, dxs, dys, dates, new_dates):
        # convert to float for interpolation
        int_new_dates = new_dates.astype(float)
        # force both dates to have the same datetime type (s, ms, ns, ...)
        int_dates = dates.astype(new_dates.dtype).astype(float)

        def build_dxdy(x, y):
            dxdy = np.zeros(y.size)

            # slope before point
            dy_b = np.diff(y[:-1]) / np.diff(x[:-1])
            # slope after point
            dy_a = np.diff(y[1:]) / np.diff(x[1:])

            # slope should be 0 everythere except :
            #   - we are strictly increasing (or decreasing) on the 3 consecutives points (before, within and after)
            dxdy[1:-1] = np.where((dy_b * dy_a > 0), np.mean([dy_b, dy_a], axis=0), 0)
            return dxdy

        # cubic hermite splice is used because it gives a result which is :
        #   continuous
        #   first derivative is continuous too
        # => it gives you a nice path without spike deplacements, smooth acceleration and decelerations
        f = interpolate.CubicHermiteSpline(int_dates, x, dydx=build_dxdy(int_dates, x))
        X = f(int_new_dates)

        f = interpolate.CubicHermiteSpline(int_dates, y, dydx=build_dxdy(int_dates, y))
        Y = f(int_new_dates)

        f = interpolate.CubicHermiteSpline(int_dates, dxs, dydx=build_dxdy(int_dates, dxs))
        new_dx = f(int_new_dates)
        f = interpolate.CubicHermiteSpline(int_dates, dys, dydx=build_dxdy(int_dates, dys))
        new_dy = f(int_new_dates)
        return new_dates, X, Y, new_dx, new_dy

    def _compute_path(self, dt):
        """compute path for the required points of interests

        Parameters
        ----------
        dt : int or numpy.timedelta64
            the unit for image computation.
            An image will be created for eath `dt` time passed

        Returns
        -------
        tuple
            return new_dates, cartopy_extent, speed
            where :
                new_dates is the date (np.datetime64) of the image, or the indice of the image
                cartopy_extent is a list of [x0, x1, y0, y1] coordinates used by ax.set_extent(...)
                speed is the camera speed between this image and the last one.
                    if dates is an np.datetime64, the speed will be `degrees / s`
                    if dates is an int, the speed will be `degrees / images`

        """
        x, y, dxs, dys, dates, new_dates = self._merge_moves(dt)
        new_dates, X, Y, new_dx, new_dy = self._interp_moves(x, y, dxs, dys, dates, new_dates)

        length = np.zeros(X.shape, dtype=np.float64)

        dist = np.sqrt((X[1:] - X[:-1]) ** 2 + (Y[1:] - Y[:-1]) ** 2)
        length[1:] = dist

        cartopy_extent = np.array([X - new_dx, X + new_dx, Y - new_dy, Y + new_dy]).T
        return new_dates, cartopy_extent, length

    ### VISUALISATION ###
    #####################

    def _build_xarray(self, dt, variables, derivative=False):
        x, y, dxs, dys, dates, new_dates = self._merge_moves(dt)
        new_dates, X, Y, new_dx, new_dy = self._interp_moves(x, y, dxs, dys, dates, new_dates)

        dates = dates.astype("datetime64[ns]")
        new_dates = new_dates.astype("datetime64[ns]")

        ds = xr.Dataset()
        kw = {"units": "degrees"}

        if derivative:
            dtime = dt / np.timedelta64(1, "D")
            ds["x"] = (["time"], (X[1:] - X[:-1]) / dtime, kw)
            ds["y"] = (["time"], (Y[1:] - Y[:-1]) / dtime, kw)
            ds["dx"] = (["time"], (new_dx[1:] - new_dx[:-1]) / dtime, kw)
            ds["dy"] = (["time"], (new_dy[1:] - new_dy[:-1]) / dtime, kw)
            ds["time"] = (["time"], new_dates[1:])
            ds = ds.set_coords(["time"])  # .rename({"time": "time"})
            ds2 = ds.interp(time=dates).rename({"time": "old_time"})

            for var in ds2.variables:
                ds[var + "_old"] = ds2[var]

        else:
            ds["x_old"] = (["old_time"], x, kw)
            ds["y_old"] = (["old_time"], y, kw)
            ds["dx_old"] = (["old_time"], dxs, kw)
            ds["dy_old"] = (["old_time"], dys, kw)
            ds["old_time"] = (["old_time"], dates)

            ds["x"] = (["time"], X, kw)
            ds["y"] = (["time"], Y, kw)
            ds["dx"] = (["time"], new_dx, kw)
            ds["dy"] = (["time"], new_dy, kw)
            ds["time"] = (["time"], new_dates)
            ds = ds.set_coords(["time", "old_time"])
        return ds

    def plot_moves(self, dt, variables=["x", "y", "dx", "dy"], derivated=False):
        """Build a matplotlib plot with different variables, to visualize the path

        Parameters
        ----------
        dt : numpy.timedelta64
            dt used to compute path. Same used in :meth:`Path._compute_path`
        variables : list, optional
            variables to show, by default ["x", "y", "dx", "dy"]

        Returns
        -------
        tuple(matplotlib.figure.Figure, matplotlib.axes.Axes)
            figure and axes used

        Raises
        ------
        ImportError
            If matplotlib not installed
        """

        try:
            import matplotlib.pyplot as plt
        except ImportError as err:
            logger.error("please install matplotlib to use this function")
            raise err

        ds = self._build_xarray(dt, variables, derivated)

        fig, axs = plt.subplots(len(variables), 1, figsize=(10, 5), dpi=120)
        for i, (ax, var) in enumerate(zip(axs, variables)):
            ax.grid()
            ds[var + "_old"].plot(
                ax=ax, label=f"real ({ds.sizes['old_time']} pts)", marker="o", x="old_time", linestyle=""
            )
            ds[var].plot(ax=ax, label=f"interpolated ({ds.sizes['time']} pts)", x="time")
            if i < len(variables) - 1:
                ax.set_xticklabels([])
            ax.legend()
        logger.error(str(ds))
        return fig, ax


class TimePath(Path):
    def __init__(self, coords=(180, 0), dx=180, dy=90, t0=0):
        datetype = type(np.datetime64("now"))

        # we should have only datetime64
        if not isinstance(t0, datetype):
            raise TypeError(f"t0 should be a `numpy.datetime64`, not '{type(t0)}'")

        super().__init__(coords, dx, dy, t0)

    @classmethod
    def _sanitize_time(cls, t):
        datetype = type(np.datetime64("now"))
        timetype = type(np.timedelta64(1, "D"))
        if not isinstance(t, (datetype, timetype)):
            logger.error(f"time shoud be type `np.datetime64` or `np.timedelta64`, not {type(t)}")
            raise TypeError("time bad type")

    def _sanitize_dt(cls, t):
        timetype = type(np.timedelta64(1, "D"))
        if not isinstance(t, timetype):
            logger.error(f"dt shoud be type `np.timedelta64`, not {type(t)}")
            raise TypeError("dt bad type")

    def _add_time(self, t):
        last_date = self._times[-1]
        if np.issubdtype(t.dtype, np.datetime64):
            date = t

        else:
            # _dt is not np.datetime64, so its a np.timedelta64 (cf _sanitize_time)
            date = last_date + t

        if date < last_date:
            raise Exception(f"time specified '{t}' make the date '{date}' before last date specified '{last_date}'")

        self._times.append(date)

    def compute_path(self, dt):
        self._sanitize_dt(dt)

        # length is in degrees / dt (could be hours, seconds or days)
        new_dates, cartopy_extent, length = self._compute_path(dt)

        # gives speed in degrees / day
        speed = length * (np.timedelta64(1, "D") / dt)

        return new_dates, cartopy_extent, speed


class FramePath(Path):
    def __init__(self, coords=(180, 0), dx=180, dy=90):
        super().__init__(coords, dx, dy, 0)

    @classmethod
    def _sanitize_time(cls, t):
        if not isinstance(t, int):
            logger.error(f"time shoud be type `int`, not {type(t)}")
            raise TypeError("time bad type")

        if t < 1:
            logger.error("time should be a int >= 1")
            raise TypeError("time bad value")

    def _add_time(self, t):
        old_frame = self._times[-1]
        self._times.append(t + old_frame)

    def compute_path(self):
        return self._compute_path(1)

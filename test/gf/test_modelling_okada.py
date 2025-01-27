from __future__ import division, print_function, absolute_import
import os
import numpy as num
import unittest

from pyrocko import util
from pyrocko import moment_tensor as pmt
from pyrocko.modelling import (
    okada_ext, OkadaSource, GriffithCrack, make_okada_coefficient_matrix,
    invert_fault_dislocations_bem)


from ..common import Benchmark

benchmark = Benchmark()

d2r = num.pi / 180.
r2d = 180. / num.pi
km = 1000.


show_plot = int(os.environ.get('MPL_SHOW', 0))


class OkadaTestCase(unittest.TestCase):

    def test_okada(self):
        n = 1

        north = num.linspace(0., 5., n)
        east = num.linspace(-5., 0., n)
        down = num.linspace(15., 5., n)

        strike = 0.
        dip = 0.
        rake = 90.
        slip = 1.0
        opening = 0.

        al1 = 0.
        al2 = 0.5
        aw1 = 0.
        aw2 = 0.25
        poisson = 0.25
        mu = 32.0e9
        lamb = (2 * poisson * mu) / (1 - 2 * poisson)

        nthreads = 0

        source_patches = num.zeros((n, 9))
        source_patches[:, 0] = north
        source_patches[:, 1] = east
        source_patches[:, 2] = down
        source_patches[:, 3] = strike
        source_patches[:, 4] = dip
        source_patches[:, 5] = al1
        source_patches[:, 6] = al2
        source_patches[:, 7] = aw1
        source_patches[:, 8] = aw2

        source_disl = num.zeros((n, 3))
        source_disl[:, 0] = num.cos(rake * d2r) * slip
        source_disl[:, 1] = num.sin(rake * d2r) * slip
        source_disl[:, 2] = opening

        receiver_coords = source_patches[:, :3].copy()

        results = okada_ext.okada(
            source_patches, source_disl, receiver_coords, lamb, mu, nthreads)

        assert results.shape == tuple((n, 12))

        source_list2 = [OkadaSource(
            lat=0., lon=0.,
            north_shift=north[i], east_shift=east[i],
            depth=down[i], al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            strike=strike, dip=dip,
            rake=rake, slip=slip, opening=opening,
            poisson=poisson, shearmod=mu)
            for i in range(n)]
        source_patches2 = num.array([
            source.source_patch() for source in source_list2])
        num.testing.assert_equal(source_patches, source_patches2)

        source_disl2 = num.array([
            patch.source_disloc() for patch in source_list2])
        num.testing.assert_equal(source_disl, source_disl2)

        results2 = okada_ext.okada(
            source_patches2, source_disl2, receiver_coords, lamb, mu, nthreads)
        num.testing.assert_equal(results, results2)

        seismic_moment = \
            mu * num.sum(num.abs([al1, al2])) * \
            num.sum(num.abs([aw1, aw2])) * num.sqrt(num.sum(
                [slip**2, opening**2]))

        assert source_list2[0].seismic_moment == seismic_moment

    def test_okada_params(self):
        strike = 0.
        dip = 0.
        rake = 90.
        slip = 1.0
        opening = 1.0

        al1 = 0.
        al2 = 0.5
        aw1 = 0.
        aw2 = 0.25
        poisson = 0.25
        mu = 32.0e9
        lamb = (2. * poisson * mu) / (1. - 2. * poisson)

        source = OkadaSource(
            lat=0., lon=0.,
            north_shift=0., east_shift=0.,
            depth=1000., al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            strike=strike, dip=dip,
            rake=rake, slip=slip, opening=opening,
            poisson=poisson, lamb=lamb)

        assert source.shearmod == mu

        source.lamb = None
        source.shearmod = mu
        assert source.lamb == lamb

        source.poisson = None
        source.lamb = lamb
        assert source.poisson == poisson

        moment = num.linalg.norm(
            (slip, opening)) * (al1 + al2) * (aw1 + aw2) * mu

        num.testing.assert_allclose(source.seismic_moment, moment, atol=1e-7)
        num.testing.assert_allclose(
            source.moment_magnitude,
            pmt.moment_to_magnitude(moment),
            atol=1e-7)

    def test_okada_online_example(self):
        source_list = [OkadaSource(
            lat=0., lon=0., north_shift=0., east_shift=0., depth=50.,
            al1=-80., al2=120., aw1=-30., aw2=25., strike=0., dip=70.,
            opening=1., slip=2.5, rake=323.130103)]

        receiver_coords = num.array([10., -20., 30.])[num.newaxis, :]
        poisson = 0.25
        mu = 32.e9
        lamb = (2 * poisson * mu) / (1 - 2 * poisson)

        u = okada_ext.okada(
            num.array([source.source_patch() for source in source_list]),
            num.array([source.source_disloc() for source in source_list]),
            receiver_coords.copy(), lamb, mu, 0)

        u_check = num.array([-0.378981, -0.631789, -0.14960])
        # Example values from:
        # http://www.bosai.go.jp/study/application/dc3d/download/DC3Dmanual.pdf

        for i in range(3):
            vals = num.array([u[0][i], u_check[i]])
            assert num.abs(u[0][i]) - num.abs(u_check[i]) < 1e-5
            assert num.all(vals > 0.) or num.all(vals < 0.)

    def test_okada_inv_benchmark(self):
        nlength = 25
        nwidth = 25

        al1 = -40.
        al2 = -al1
        aw1 = -20.
        aw2 = -aw1

        strike = 0.
        dip = 70.

        ref_north = 100.
        ref_east = 200.
        ref_depth = 50.

        source = OkadaSource(
            lat=1., lon=-1., north_shift=ref_north, east_shift=ref_east,
            depth=ref_depth,
            al1=al1, al2=al2, aw1=aw1, aw2=aw2, strike=strike, dip=dip)

        source_disc, _ = source.discretize(nlength, nwidth)

        @benchmark.labeled('okada_inv')
        def calc():
            return make_okada_coefficient_matrix(
                source_disc, nthreads=6)

        @benchmark.labeled('okada_inv_single')
        def calc_bulk():
            return make_okada_coefficient_matrix(
                source_disc, nthreads=6, variant='single')

        @benchmark.labeled('okada_slow')
        def calc_slow():
            return make_okada_coefficient_matrix(
                source_disc, nthreads=6, variant='slow')

        res1 = calc()
        # res1 = calc()
        # res2 = calc_bulk()
        # res3 = calc_slow()

        @benchmark.labeled('mat_inversion')
        def inv():
            num.linalg.inv(num.dot(res1.T, res1))

        res = res1.copy()

        @benchmark.labeled('mat_inversion_sparse')
        def inv_sparse():
            res[res < 1e-2] = 0.
            num.linalg.inv(num.dot(res.T, res))

        inv()
        inv_sparse()
        # num.testing.assert_equal(res1, res2)
        # num.testing.assert_equal(res2, res3)
        print(benchmark)

    def test_okada_rotate_sdn(self):
        nlength = 35
        nwidth = 25

        al1 = -40.
        al2 = -al1
        aw1 = -20.
        aw2 = -aw1

        strike = 0.
        dip = 70.

        ref_north = 100.
        ref_east = 200.
        ref_depth = 50.

        source = OkadaSource(
            lat=1., lon=-1., north_shift=ref_north, east_shift=ref_east,
            depth=ref_depth,
            al1=al1, al2=al2, aw1=aw1, aw2=aw2, strike=strike, dip=dip)

        source_disc, _ = source.discretize(nlength, nwidth)
        npoints = len(source_disc)

        source_patches = num.array([
            src.source_patch() for src in source_disc])
        receiver_coords = source_patches[:, :3].copy()
        coefmat = num.zeros((npoints * 3, npoints * 3))
        coefmat_sdn = num.zeros((npoints * 3, npoints * 3))

        def ned2sdn_rotmat(strike, dip):
            return pmt.euler_to_matrix((dip + 180.)*d2r, strike*d2r, 0.)

        lambda_mean = num.mean([src.lamb for src in source_disc])
        mu_mean = num.mean([src.shearmod for src in source_disc])

        case = {
            'slip': 1.,
            'opening': 0.,
            'rake': 0.
        }

        diag_ind = (0, 4, 8)
        kron = num.zeros((npoints, 9))
        kron[:, diag_ind] = 1.

        source_disl = num.array([
            case['slip'] * num.cos(case['rake'] * d2r),
            case['slip'] * num.sin(case['rake'] * d2r),
            case['opening']])

        # Python rotation to sdn
        for isource, source in enumerate(source_patches):
            results = okada_ext.okada(
                source.reshape(1, -1),
                source_disl.reshape(1, -1),
                receiver_coords,
                lambda_mean,
                mu_mean,
                nthreads=0,
                rotate_sdn=False)

            eps = \
                0.5 * (
                    results[:, 3:] +
                    results[:, (3, 6, 9, 4, 7, 10, 5, 8, 11)])

            dilatation = num.sum(eps[:, diag_ind], axis=1)[:, num.newaxis]

            stress_ned = kron * lambda_mean * dilatation+2. * mu_mean * eps
            rotmat = ned2sdn_rotmat(
                source_disc[isource].strike,
                source_disc[isource].dip)

            kwargs = {}
            if num.__version__ >= '1.12.0':
                kwargs['optimize'] = True

            stress_sdn = num.einsum(
                'ij,...jk,lk->...il',
                rotmat, stress_ned.reshape(npoints, 3, 3), rotmat,
                **kwargs)

            stress_sdn = stress_sdn.reshape(npoints, 9)

            coefmat[0::3, isource * 3] = -stress_sdn[:, 2].ravel()
            coefmat[1::3, isource * 3] = -stress_sdn[:, 5].ravel()
            coefmat[2::3, isource * 3] = -stress_sdn[:, 8].ravel()

        # c-ext rotation to sdn
        for isource, source in enumerate(source_patches):
            results = okada_ext.okada(
                source.reshape(1, -1),
                source_disl.reshape(1, -1),
                receiver_coords,
                lambda_mean,
                mu_mean,
                nthreads=0,
                rotate_sdn=True)

            eps = \
                0.5 * (
                    results[:, 3:] +
                    results[:, (3, 6, 9, 4, 7, 10, 5, 8, 11)])

            dilatation = num.sum(eps[:, diag_ind], axis=1)[:, num.newaxis]

            stress_sdn = kron * lambda_mean * dilatation+2. * mu_mean * eps

            coefmat_sdn[0::3, isource * 3] = -stress_sdn[:, 2].ravel()
            coefmat_sdn[1::3, isource * 3] = -stress_sdn[:, 5].ravel()
            coefmat_sdn[2::3, isource * 3] = -stress_sdn[:, 8].ravel()

        num.testing.assert_allclose(coefmat, coefmat_sdn)

    def test_okada_discretize(self):
        nlength = 100
        nwidth = 10

        al1 = -80.
        al2 = -al1
        aw1 = -30.
        aw2 = -aw1

        strike = 0.
        dip = 70.

        ref_north = 100.
        ref_east = 200.
        ref_depth = 50.

        source = OkadaSource(
            lat=1., lon=-1., north_shift=ref_north, east_shift=ref_east,
            depth=ref_depth,
            al1=al1, al2=al2, aw1=aw1, aw2=aw2, strike=strike, dip=dip)

        source_disc, _ = source.discretize(nlength, nwidth)

        al1_patch = al1 / nlength
        al2_patch = al2 / nlength
        aw1_patch = aw1 / nwidth
        aw2_patch = aw2 / nwidth

        patch_length = num.sum(num.abs([al1_patch, al2_patch]))
        patch_width = num.sum(num.abs([aw1_patch, aw2_patch]))

        source_coords = num.zeros((nlength * nwidth, 3))
        for iw in range(nwidth):
            for il in range(nlength):
                idx = iw * nlength + il
                x = il * patch_length + num.abs(al1_patch) + al1
                y = iw * patch_width + num.abs(aw1_patch) - aw2

                source_coords[idx, 0] = \
                    num.cos(strike * d2r) * x - \
                    num.sin(strike * d2r) * num.cos(dip * d2r) * y
                source_coords[idx, 1] = \
                    num.sin(strike * d2r) * x + \
                    num.cos(strike * d2r) * num.cos(dip * d2r) * y
                source_coords[idx, 2] = \
                    num.sin(dip * d2r) * y

        source_coords[:, 0] += ref_north
        source_coords[:, 1] += ref_east
        source_coords[:, 2] += ref_depth

        num.testing.assert_allclose(
            source_coords,
            num.array([
                [src.north_shift, src.east_shift, src.depth]
                for src in source_disc]),
            rtol=1e1)

        if show_plot:
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d import Axes3D # noqa

            fig = plt.figure()
            ax = fig.add_subplot(1, 1, 1, projection='3d')
            ax.scatter(
                [src.east_shift for src in source_disc],
                [src.north_shift for src in source_disc],
                zs=[-src.depth for src in source_disc], s=20)
            ax.scatter(
                [ref_east], [ref_north], zs=[-ref_depth], s=200, c='red')
            plt.axis('equal')
            plt.show()

    def test_okada_gf_fill(self):
        ref_north = 0.
        ref_east = 0.
        ref_depth = 100*km

        nlength = 10
        nwidth = 10

        strike = 0.
        dip = 90.
        length = 0.5
        width = 0.5
        length_total = nlength * length
        width_total = nwidth * width

        al1 = -length_total / 2.
        al2 = length_total / 2.
        aw1 = -width_total / 2.
        aw2 = width_total / 2.
        poisson = 0.25
        mu = 32.0e9

        source = OkadaSource(
            lat=0., lon=0.,
            north_shift=ref_north, east_shift=ref_east,
            depth=ref_depth, al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            strike=strike, dip=dip, rake=0.,
            shearmod=mu, poisson=poisson)

        source_list, _ = source.discretize(nlength, nwidth)

        receiver_coords = num.array([
            src.source_patch()[:3] for src in source_list])

        pure_shear = True
        if pure_shear:
            n_eq = 2
        else:
            n_eq = 3

        gf = make_okada_coefficient_matrix(
            source_list, pure_shear=pure_shear)
        gf2 = make_okada_coefficient_matrix(
            source_list, pure_shear=pure_shear, variant='single')

        assert num.linalg.slogdet(num.dot(gf.T, gf)) != (0., num.inf)
        assert num.linalg.slogdet(num.dot(gf2.T, gf2)) != (0., num.inf)
        num.testing.assert_equal(gf, gf2)

        # Function to test the computed GF
        dstress = -1.5e6
        stress_comp = 1

        stress = num.full(nlength * nwidth * 3, dstress)
        for iw in range(nwidth):
            for il in range(nlength):
                idx = iw * nlength + il
                if (il > 2 and il < 10) and (iw > 2 and iw < 12):
                    stress[idx * 3 + stress_comp] = dstress / 4.

        @benchmark.labeled('lsq')
        def lsq():
            return invert_fault_dislocations_bem(
                stress, coef_mat=gf, pure_shear=pure_shear)

        disloc_est = lsq()

        if show_plot:
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d import Axes3D # noqa

            def add_subplot(fig, ntot, n, param, title, **kwargs):
                ax = fig.add_subplot(ntot, 1, n, projection='3d')
                scat = ax.scatter(
                    receiver_coords[:, 1], receiver_coords[:, 0],
                    zs=-receiver_coords[:, 2], zdir='z', s=20,
                    c=num.array(param), cmap='jet',
                    edgecolor='None', **kwargs)
                fig.colorbar(scat, shrink=0.5, aspect=5)
                ax.set_title(title)

            param = disloc_est
            vmin = num.min(param)
            vmax = num.max(param)

            fig = plt.figure()
            add_subplot(
                fig, n_eq + 1, 1, [i for i in stress[stress_comp::n_eq]],
                'stress')
            add_subplot(
                fig, n_eq + 1, 2, [i for i in param[::n_eq]],
                '$u_{strike}$', vmin=vmin, vmax=vmax)
            add_subplot(
                fig, n_eq + 1, 3, [i for i in param[1::n_eq]],
                '$u_{dip}$', vmin=vmin, vmax=vmax)
            if n_eq == 3:
                add_subplot(
                    fig, n_eq + 1, 4, [i for i in param[2::n_eq]],
                    '$u_{opening}$', vmin=vmin, vmax=vmax)
            plt.show()

        print(benchmark)

    def test_okada_vs_griffith_inf2d(self):
        from pyrocko.modelling import GriffithCrack

        length_total = 100000.
        width_total = 10000.

        nlength = 3
        nwidth = 101
        length = length_total / nlength
        width = width_total / nwidth

        al1 = -length / 2.
        al2 = length / 2.
        aw1 = -width / 2.
        aw2 = width / 2.
        poisson = 0.25
        mu = 32.0e9

        dstress = -0.5e6
        stress_comp = 2
        min_x = -width_total / 2.
        max_x = width_total / 2.

        npoints = nlength * nwidth

        source_coords = num.zeros((npoints, 3))
        stress = num.zeros((npoints * 3, ))
        for iw in range(nwidth):
            for il in range(nlength):
                idx = iw * nlength + il
                source_coords[idx, 0] = \
                    il * length - (nlength - 1) / 2. * length
                source_coords[idx, 1] = \
                    iw * width - (nwidth - 1) / 2. * width
                stress[idx * 3 + stress_comp] = dstress

        source_coords[:, 2] = 100000.
        receiver_coords = source_coords.copy()

        source_list = [OkadaSource(
            lat=0., lon=0.,
            north_shift=coords[0], east_shift=coords[1],
            depth=coords[2], al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            strike=0., dip=0., rake=0.,
            shearmod=mu, poisson=poisson) for coords in source_coords]

        gf = make_okada_coefficient_matrix(source_list, pure_shear=False)
        disloc_est = invert_fault_dislocations_bem(
            stress, coef_mat=gf).ravel()

        stressdrop = num.zeros(3, )
        stressdrop[stress_comp] = dstress
        rec_grif = num.linspace(min_x - aw1, max_x - aw2, nwidth)

        griffith = GriffithCrack(
            width=num.sum(num.abs([min_x, max_x])),
            poisson=poisson,
            shearmod=mu,
            stressdrop=stressdrop)

        disloc_grif = griffith.disloc_infinite2d(x_obs=rec_grif)

        line = int(nlength / 2)
        idx = line
        idx2 = (nwidth - 1) * nlength + line + 1

        num.testing.assert_allclose(
            disloc_grif[:, 2],
            disloc_est[idx * 3 + 2:idx2 * 3 + 2:3 * nlength],
            atol=1e-2)

        if show_plot:
            import matplotlib.pyplot as plt

            def add_subplot(fig, ntot, n, title, comp, typ='line'):
                ax = fig.add_subplot(ntot, 1, n)
                if typ == 'line':
                    ax.plot(
                        receiver_coords[idx:idx2:nlength, 1],
                        disloc_est[idx * 3 + comp:idx2 * 3 + comp:3 * nlength],
                        'b-', label='Okada solution')
                    ax.plot(
                        rec_grif,
                        disloc_grif[:, comp],
                        'r-', label='Griffith crack sol.')
                    plt.legend()
                elif typ == 'scatter':
                    scat = ax.scatter(
                        receiver_coords[:, 1], receiver_coords[:, 0],
                        c=num.array([i for i in disloc_est[comp::3]]))
                    fig.colorbar(scat, shrink=0.8, aspect=5)
                    plt.axis('equal')
                ax.set_title(title)

            fig = plt.figure()
            add_subplot(
                fig, 3, 1, r'$\Delta u_{strike}$ along profile %i' % line, 0)
            add_subplot(fig, 3, 2, r'$\Delta u_{dip}$', 1)
            add_subplot(fig, 3, 3, r'$\Delta u_{normal}$', 2)

            fig = plt.figure()
            add_subplot(fig, 3, 1, r'$\Delta u_{strike}$', 0, typ='scatter')
            add_subplot(fig, 3, 2, r'$\Delta u_{dip}$', 1, typ='scatter')
            add_subplot(fig, 3, 3, r'$\Delta u_{normal}$', 2, typ='scatter')
            plt.show()

    def test_okada_vs_griffith_circ(self):
        length_total = 10000.
        width_total = length_total

        nlength = 21
        nwidth = nlength
        length = length_total / nlength
        width = width_total / nwidth

        al1 = -length / 2.
        al2 = length / 2.
        aw1 = -width / 2.
        aw2 = width / 2.
        poisson = 0.25
        mu = 32.0e9

        dstress = -0.5e6
        radius = length_total / 2.

        source_coords = []
        stress = []
        for iw in range(nwidth):
            for il in range(nlength):
                coords = num.zeros(3)
                coords[0] = \
                    il * length - (nlength - 1) / 2. * length
                coords[1] = \
                    iw * width - (nwidth - 1) / 2. * width

                if num.sqrt(num.sum([
                        (coords[1])**2., (coords[0])**2.])) <= radius:

                    source_coords.append(coords)
                    stress.append(num.array([0., 0., dstress]))

        source_coords = num.array(source_coords)
        stress = num.array(stress).flatten()

        source_coords[:, 2] = 200000.
        receiver_coords = source_coords.copy()

        source_list = [OkadaSource(
            lat=0., lon=0.,
            north_shift=src_crds[0], east_shift=src_crds[1],
            depth=src_crds[2], al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            strike=0., dip=0., rake=0.,
            shearmod=mu, poisson=poisson) for src_crds in source_coords]

        gf = make_okada_coefficient_matrix(source_list, pure_shear=False)
        disloc_est = invert_fault_dislocations_bem(
            stress, coef_mat=gf).ravel()

        stressdrop = num.zeros(3, )
        stressdrop[2] = dstress
        rec_grif = num.linspace(-radius - aw1, radius - aw2, nwidth)

        griffith = GriffithCrack(
            width=length_total,
            poisson=poisson, shearmod=mu, stressdrop=stressdrop)

        # Test circular crack
        disloc_grif = griffith.disloc_circular(x_obs=rec_grif)

        indices = num.arange(source_coords.shape[0])[source_coords[:, 0] == 0.]
        line = int(nlength / 2.)

        num.testing.assert_allclose(
            disloc_grif[:, 2],
            disloc_est[indices * 3 + 2],
            atol=1e-2)

        if show_plot:
            import matplotlib.pyplot as plt

            def add_subplot(fig, ntot, n, title, comp, typ='line'):
                ax = fig.add_subplot(ntot, 1, n)
                if typ == 'line':
                    ax.plot(
                        receiver_coords[indices, 1],
                        disloc_est[indices * 3 + comp],
                        'b-', label='Okada solution')
                    ax.plot(
                        rec_grif,
                        disloc_grif[:, comp],
                        'r-', label='Griffith crack sol.')
                    plt.legend()
                elif typ == 'scatter':
                    scat = ax.scatter(
                        receiver_coords[:, 1], receiver_coords[:, 0],
                        c=num.array([i for i in disloc_est[comp::3]]))
                    artist = plt.Circle((0, 0), radius - al2, fill=False)
                    ax.add_artist(artist)
                    fig.colorbar(scat, shrink=0.8, aspect=5)
                    plt.axis('equal')
                ax.set_title(title)

            fig = plt.figure()
            add_subplot(
                fig, 3, 1, r'$\Delta u_{strike}$ along profile %i' % line, 0)
            add_subplot(fig, 3, 2, r'$\Delta u_{dip}$', 1)
            add_subplot(fig, 3, 3, r'$\Delta u_{normal}$', 2)

            fig = plt.figure()
            add_subplot(fig, 3, 1, r'$\Delta u_{strike}$', 0, typ='scatter')
            add_subplot(fig, 3, 2, r'$\Delta u_{dip}$', 1, typ='scatter')
            add_subplot(fig, 3, 3, r'$\Delta u_{normal}$', 2, typ='scatter')
            plt.show()

    def test_okada_vs_griffith_displacement_inf2d(self):
        length_total = 50. * km
        width_total = 10. * km
        depth = 200. * km

        al1 = -length_total / 2.
        al2 = length_total / 2.
        aw1 = -width_total / 2.
        aw2 = width_total / 2.

        nlength = 50
        nwidth = 10

        poisson = 0.25
        mu = 32.0e9
        lamb = (2. * poisson * mu) / (1. - 2. * poisson)

        dstress = -0.5e6
        comp = 1
        min_x = -width_total / 2.
        max_x = width_total / 2.

        source = OkadaSource(
            lat=0., lon=0.,
            north_shift=0., east_shift=0.,
            depth=depth, al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            strike=0., dip=0., rake=0.,
            shearmod=mu, poisson=poisson)

        source_list, _ = source.discretize(nlength, nwidth)

        for isource in range(len(source_list)):
            source_list[isource].shearmod = mu
            source_list[isource].poisson = poisson

        # Displacement along x2
        stress = num.zeros((3 * len(source_list), ))
        stress[comp::3] = dstress

        cf = make_okada_coefficient_matrix(source_list, pure_shear=False)

        disloc_okada = invert_fault_dislocations_bem(
            stress_field=stress,
            coef_mat=cf)

        source_patches = num.array([src.source_patch() for src in source_list])
        source_disl = disloc_okada.reshape(source_patches.shape[0], 3)

        n_rec = 30
        x_grif = num.linspace(min_x * 3., max_x * 3., n_rec)

        receiver_coords = num.zeros((n_rec, 3))
        receiver_coords[:, 0] = 0.
        receiver_coords[:, 1] = x_grif
        receiver_coords[:, 2] = depth

        displ_okada = okada_ext.okada(
            source_patches, source_disl, receiver_coords, lamb, mu, 0)

        stressdrop = num.zeros(3, )
        stressdrop[comp] = dstress

        griffith = GriffithCrack(
            width=num.sum(num.abs([min_x, max_x])),
            poisson=poisson,
            shearmod=mu,
            stressdrop=stressdrop)

        displ_grif = griffith.displ_infinite2d(x1_obs=0., x2_obs=x_grif)

        num.testing.assert_allclose(
            displ_grif[:, 2],
            displ_okada[:, 2],
            rtol=4e-1)

        if show_plot:
            import matplotlib.pyplot as plt

            plt.plot(x_grif, displ_grif[:, 2], 'r')
            plt.plot(x_grif, displ_okada[:, 2], 'b')

            plt.xlabel('distance along x2 [m]')
            plt.ylabel('opening displacement [m]')

            plt.show()

        # Displacement along x1
        comp = 0
        stress = num.zeros((3 * len(source_list), ))
        stress[comp::3] = dstress

        stressdrop = num.zeros(3, )
        stressdrop[comp] = dstress

        griffith.stressdrop = stressdrop

        for i in range(len(source_list)):
            source_list[i].depth = depth

        cf = make_okada_coefficient_matrix(source_list)
        disloc_okada = invert_fault_dislocations_bem(
                stress_field=stress,
                coef_mat=cf)

        source_patches = num.array([src.source_patch() for src in source_list])
        source_disl = disloc_okada.reshape(source_patches.shape[0], 3)

        n_rec = 30
        receiver_coords = num.zeros((n_rec, 3))
        receiver_coords[:, 0] = 0.
        receiver_coords[:, 1] = 0.
        receiver_coords[:, 2] = depth + x_grif

        displ_okada = okada_ext.okada(
            source_patches, source_disl, receiver_coords, lamb, mu, 0)

        displ_grif = -griffith.displ_infinite2d(x1_obs=x_grif, x2_obs=0.)

        num.testing.assert_allclose(
            displ_grif[:, 0],
            displ_okada[:, 0],
            rtol=5e-1)

        if show_plot:
            import matplotlib.pyplot as plt

            plt.plot(x_grif, displ_grif[:, 0], 'r')
            plt.plot(x_grif, displ_okada[:, 0], 'b')

            plt.xlabel('distance along x1 [m]')
            plt.ylabel('displacement in strike [m]')

            plt.show()

    def test_patch2m6(self):
        rstate = num.random.RandomState(123)
        nbasesrcs = 100
        strike = 132.
        dip = 13.
        lamb = 12.
        mu = 4.3

        slip_rake = rstate.uniform(0., 2*num.pi, nbasesrcs)
        slip_shear = rstate.uniform(0., 1., nbasesrcs)
        slip_norm = rstate.uniform(0., 1., nbasesrcs)

        m6s = okada_ext.patch2m6(
            strikes=num.full(nbasesrcs, strike),
            dips=num.full(nbasesrcs, dip),
            rakes=slip_rake*r2d,
            disl_shear=slip_shear,
            disl_norm=slip_norm,
            lamb=num.repeat(lamb, nbasesrcs),
            mu=num.repeat(mu, nbasesrcs))

        def patch2m6(strike, dip, rake, du_s, du_n):
            rotmat = pmt.euler_to_matrix(dip, strike, -rake)
            momentmat = num.array(
                [[lamb * du_n, 0.,          -mu * du_s],
                 [0.,          lamb * du_n, 0.],
                 [-mu * du_s,  0.,          (lamb + 2. * mu) * du_n]])
            return pmt.to6(num.dot(rotmat.T, num.dot(momentmat, rotmat)))

        m6s_old = num.array([
            patch2m6(
                strike * d2r, dip * d2r, rake=slip_rake[im],
                du_s=slip_shear[im], du_n=slip_norm[im])
            for im in range(nbasesrcs)])

        num.testing.assert_almost_equal(m6s, m6s_old)


if __name__ == '__main__':
    util.setup_logging('test_okada', 'warning')
    unittest.main()

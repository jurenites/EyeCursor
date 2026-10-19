"""Conservative image-space iris support and robust eye-center estimation.

These estimates are camera projections, not anatomical measurements. An absent
iris boundary or ill-conditioned center fit is explicitly reported as unavailable.
"""
import math
from itertools import combinations
import cv2
import numpy as np


def ellipse_normal(ellipse):
    """Projected normal follows the minor axis; circular fits have no orientation."""
    (x, y), (a, b), angle = ellipse
    if not np.isfinite([x, y, a, b, angle]).all() or min(a, b) <= 0:
        return None
    ratio = min(a, b) / max(a, b)
    if ratio > .94 or ratio < .25:
        return None
    theta = math.radians(angle + (90 if a > b else 0))
    return np.array([math.cos(theta), math.sin(theta)]), 1 - ratio


def fit_eye_center(ellipses, shape):
    """Robust deterministic line consensus; reject weak coverage and bad residuals."""
    rows, offsets, weights, centers = [], [], [], []
    for ellipse in ellipses:
        normal = ellipse_normal(ellipse)
        if normal is None:
            continue
        direction, weight = normal
        perpendicular = np.array([-direction[1], direction[0]])
        center = np.array(ellipse[0], dtype=float)
        rows.append(perpendicular)
        offsets.append(perpendicular @ center)
        weights.append(weight)
        centers.append(center)
    if len(rows) < 12:
        return None
    a, b, base, centers = map(np.array, (rows, offsets, weights, centers))
    if np.min(np.ptp(np.percentile(centers, [10, 90], axis=0), axis=0)) < 8:
        return None
    # Generate bounded deterministic candidates; one bad ray cannot drag the mean.
    indices = np.unique(np.linspace(0, len(a) - 1, min(24, len(a))).astype(int))
    ii, jj = np.triu_indices(len(indices), 1)
    first, second = a[indices[ii]], a[indices[jj]]
    bi, bj = b[indices[ii]], b[indices[jj]]
    determinant = first[:, 0] * second[:, 1] - first[:, 1] * second[:, 0]
    keep = np.abs(determinant) >= .2
    if not keep.any():
        return None
    first, second, bi, bj, determinant = (v[keep] for v in (first, second, bi, bj, determinant))
    candidates = np.column_stack(((bi * second[:, 1] - first[:, 1] * bj) / determinant,
                                  (first[:, 0] * bj - bi * second[:, 0]) / determinant))
    candidates = candidates[(candidates[:, 0] >= 0) & (candidates[:, 0] < shape[1])
                            & (candidates[:, 1] >= 0) & (candidates[:, 1] < shape[0])]
    if len(candidates) == 0:
        return None
    residuals = np.abs(a @ np.array(candidates).T - b[:, None])
    best = int(np.argmin(np.median(residuals, axis=0)))
    point = candidates[best]
    for _ in range(4):
        residual = np.abs(a @ point - b)
        cutoff = max(3., min(10., 2.5 * np.median(residual)))
        robust = base * np.minimum(1., cutoff / np.maximum(residual, .001)) ** 2
        matrix = a.T @ (robust[:, None] * a)
        if np.linalg.cond(matrix) > 25:
            return None
        point = np.linalg.solve(matrix, a.T @ (robust * b))
    residual = np.abs(a @ point - b)
    inliers = residual <= 5
    if inliers.sum() < 12 or np.mean(inliers) < .65 or np.median(residual) > 4:
        return None
    if np.linalg.cond(a[inliers].T @ a[inliers]) > 20:
        return None
    if not (0 <= point[0] < shape[1] and 0 <= point[1] < shape[0]):
        return None
    return {'center': point.tolist(), 'inliers': int(inliers.sum()),
            'residual_px': float(np.median(residual))}


def trace_iris(gray, pupil):
    """Trace outward dark-to-light edges around a pupil, excluding eyelid poles.

Both lateral arcs must support one enclosing ellipse. This never synthesizes a
pupil during a blink or upgrades confidence merely because an oval can be fitted.
"""
    if pupil is None:
        return None
    (cx, cy), (a, b), angle = pupil
    if not np.isfinite([cx, cy, a, b, angle]).all() or min(a, b) < 8:
        return None
    angles = np.linspace(0, 2 * np.pi, 96, endpoint=False)
    angles = angles[np.abs(np.sin(angles)) < .88]
    directions = np.column_stack((np.cos(angles), np.sin(angles)))
    theta = math.radians(angle)
    local_x = directions[:, 0] * math.cos(theta) + directions[:, 1] * math.sin(theta)
    local_y = -directions[:, 0] * math.sin(theta) + directions[:, 1] * math.cos(theta)
    pupil_radius = 1 / np.sqrt((local_x / (a / 2)) ** 2 + (local_y / (b / 2)) ** 2)
    scales = np.linspace(1.35, 3.5, 80)
    radii = pupil_radius[:, None] * scales
    xx = (cx + radii * directions[:, 0, None]).astype(np.float32)
    yy = (cy + radii * directions[:, 1, None]).astype(np.float32)
    smooth = cv2.GaussianBlur(gray, (5, 5), 0)
    inner = cv2.remap(smooth, xx - 3 * directions[:, 0, None].astype(np.float32),
                      yy - 3 * directions[:, 1, None].astype(np.float32), cv2.INTER_LINEAR).astype(float)
    outer = cv2.remap(smooth, xx + 3 * directions[:, 0, None].astype(np.float32),
                      yy + 3 * directions[:, 1, None].astype(np.float32), cv2.INTER_LINEAR).astype(float)
    gradient = outer - inner
    gx = cv2.remap(cv2.Sobel(smooth, cv2.CV_32F, 1, 0), xx, yy, cv2.INTER_LINEAR)
    gy = cv2.remap(cv2.Sobel(smooth, cv2.CV_32F, 0, 1), xx, yy, cv2.INTER_LINEAR)
    alignment = (gx * directions[:, 0, None] + gy * directions[:, 1, None]) / np.maximum(1, np.hypot(gx, gy))
    # Eyelids often cross the search rays: their gradient is not radial.
    gradient[alignment < .85] = -1
    valid = (xx > 5) & (yy > 5) & (xx < gray.shape[1] - 5) & (yy < gray.shape[0] - 5)
    gradient[~valid] = -1
    best = np.argmax(gradient, axis=1)
    strength = gradient[np.arange(len(best)), best]
    keep = strength >= 12
    points = np.column_stack((xx[np.arange(len(best)), best], yy[np.arange(len(best)), best]))[keep]
    angles = angles[keep]
    if len(points) < 24:
        return None
    for _ in range(3):
        if len(points) < 20:
            return None
        ellipse = cv2.fitEllipse(points.astype(np.float32))
        (ix, iy), (ia, ib), rotation = ellipse
        if min(ia, ib) <= 0:
            return None
        phi = math.radians(rotation)
        delta = points - [ix, iy]
        u = delta[:, 0] * math.cos(phi) + delta[:, 1] * math.sin(phi)
        v = -delta[:, 0] * math.sin(phi) + delta[:, 1] * math.cos(phi)
        residual = np.abs(np.sqrt((2*u/ia)**2 + (2*v/ib)**2) - 1)
        inliers = residual < .06
        if inliers.all():
            break
        points, angles = points[inliers], angles[inliers]
    if len(points) < 24:
        return None
    ellipse = cv2.fitEllipse(points.astype(np.float32))
    (ix, iy), (ia, ib), rotation = ellipse
    if (min(ia, ib) < 1.25 * min(a, b) or max(ia, ib) > 3.6 * max(a, b)
            or min(ia, ib) / max(ia, ib) < .4
            or math.hypot(ix-cx, iy-cy) > .35 * min(a, b)
            or np.count_nonzero(np.cos(angles) > .5) < 8
            or np.count_nonzero(np.cos(angles) < -.5) < 8
            or np.count_nonzero(np.sin(angles) > .2) < 6
            or np.count_nonzero(np.sin(angles) < -.2) < 6):
        return None
    # Enclosure in the fitted iris coordinates is required even with perspective.
    phi = math.radians(rotation)
    t = np.linspace(0, 2*np.pi, 24, endpoint=False)
    px = cx + a/2*np.cos(t)*math.cos(theta) - b/2*np.sin(t)*math.sin(theta) - ix
    py = cy + a/2*np.cos(t)*math.sin(theta) + b/2*np.sin(t)*math.cos(theta) - iy
    u, v = px*math.cos(phi)+py*math.sin(phi), -px*math.sin(phi)+py*math.cos(phi)
    if np.max((2*u/ia)**2 + (2*v/ib)**2) > .9:
        return None
    return {'ellipse': ellipse, 'support': min(1., len(points)/64), 'edge_points': points.tolist()}


def pupil_edge_support(gray, ellipse, bright_limit=240, edge_distance=3):
    """Fraction of boundary with dark-inside/light-outside evidence, ignoring glints."""
    center, axes, angle = ellipse
    radii = np.asarray(axes, dtype=float) / 2
    theta = math.radians(angle)
    rotation = np.array([[math.cos(theta), -math.sin(theta)],
                         [math.sin(theta), math.cos(theta)]])
    angles = np.linspace(0, 2*np.pi, 72, endpoint=False)
    unit = np.column_stack((np.cos(angles), np.sin(angles)))
    points = (unit*radii) @ rotation.T + center
    normals = (unit/radii) @ rotation.T
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    def sample(offset):
        xy = (points + offset*normals).astype(np.float32)
        return cv2.remap(gray, xy[:,0,None], xy[:,1,None], cv2.INTER_LINEAR).ravel().astype(float)
    inner, outer = sample(-edge_distance), sample(edge_distance)
    margin = edge_distance+1
    visible = ((points[:,0] > margin) & (points[:,0] < gray.shape[1]-margin)
               & (points[:,1] > margin) & (points[:,1] < gray.shape[0]-margin))
    good = visible & (outer-inner >= 8) & (inner < bright_limit) & (outer < bright_limit)
    # A bright eyelid or a single remaining crescent cannot establish a whole pupil.
    balanced = all(np.count_nonzero(good & mask) >= 5 for mask in
                   (unit[:,0] > .3, unit[:,0] < -.3, unit[:,1] > .3, unit[:,1] < -.3))
    return float(np.mean(good)) if balanced else 0.


def detect_pupil_in_iris(gray, iris):
    # A dark-only fit can confidently follow a smaller patch inside a reflected
    # pupil. Prefer a verified full boundary when contrast reversal is present.
    result = detect_reflected_pupil(gray, iris)
    return result if result is not None else _detect_dark_pupil_in_iris(gray, iris)


def _detect_dark_pupil_in_iris(gray, iris):
    """Find current pupil edges inside a verified iris, without a darkest seed.

    Normalize the iris to a unit circle, then fit a smaller circle to balanced
    dark-to-light arcs. The center can move independently, but the projected
    pupil shares the iris axis ratio and rotation. No temporal pupil is emitted.
    """
    if not iris or iris.get('support', 0) < .65:
        return None
    center, axes, angle = iris['ellipse']
    if (not np.isfinite([*center, *axes, angle]).all() or min(axes) < 24
            or min(axes)/max(axes) < .4):
        return None
    theta = math.radians(angle)
    rotation = np.array([[math.cos(theta), -math.sin(theta)],
                         [math.sin(theta), math.cos(theta)]])
    radii = np.asarray(axes)/2
    angles = np.linspace(0, 2*np.pi, 96, endpoint=False)
    unit = np.column_stack((np.cos(angles), np.sin(angles)))
    scales = np.linspace(.12, .80, 100)
    points = (unit*radii)[:, None, :]*scales[None, :, None] @ rotation.T + center
    normals = (unit/radii) @ rotation.T
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    smooth = cv2.GaussianBlur(gray, (5, 5), 1)

    def sample(image, xy):
        xy = np.asarray(xy, dtype=np.float32)
        return cv2.remap(image, xy[..., 0], xy[..., 1], cv2.INTER_LINEAR).astype(float)

    ring = ((unit*radii*.85) @ rotation.T + center)[:, None, :]
    background = float(np.median(sample(smooth, ring)))
    bright_limit = min(240, background+max(18, .35*background))
    distance = max(3, min(6, min(axes)*.025))
    inner = sample(smooth, points-distance*normals[:, None, :])
    outer = sample(smooth, points+distance*normals[:, None, :])
    gx = sample(cv2.Sobel(smooth, cv2.CV_32F, 1, 0), points)
    gy = sample(cv2.Sobel(smooth, cv2.CV_32F, 0, 1), points)
    alignment = (gx*normals[:, 0, None]+gy*normals[:, 1, None])/np.maximum(1, np.hypot(gx, gy))
    visible = ((points[..., 0] > distance+1) & (points[..., 0] < gray.shape[1]-distance-1)
               & (points[..., 1] > distance+1) & (points[..., 1] < gray.shape[0]-distance-1))
    gradient = outer-inner
    # Break broad finite-difference plateaus at the local gradient maximum.
    gradient += .05*np.hypot(gx, gy)
    gradient[(inner >= bright_limit) | (outer >= bright_limit) | ~visible | (alignment < .8)] = -1
    best = np.argmax(gradient, axis=1)
    keep = gradient[np.arange(len(unit)), best] >= 8
    boundary = points[np.arange(len(unit)), best][keep]
    if len(boundary) < 40:
        return None
    local = (boundary-center) @ rotation/radii

    # Bounded deterministic circle consensus discards eyelids and iris texture.
    ids = np.linspace(0, len(local)-1, min(16, len(local))).astype(int)
    triples = np.array(list(combinations(ids, 3)))
    a, b, c = (local[triples[:, i]] for i in range(3))
    u, v = b-a, c-a
    d = 2*(u[:, 0]*v[:, 1]-u[:, 1]*v[:, 0])
    valid = np.abs(d) > 1e-5
    a, u, v, d = (x[valid] for x in (a, u, v, d))
    if not len(d):
        return None
    uu, vv = np.sum(u*u, axis=1), np.sum(v*v, axis=1)
    centers = a+np.column_stack((uu*v[:, 1]-vv*u[:, 1], u[:, 0]*vv-v[:, 0]*uu))/d[:, None]
    sizes = np.linalg.norm(centers-a, axis=1)
    valid = ((sizes >= .18) & (sizes <= .72) & (np.linalg.norm(centers, axis=1) <= .22)
             & (np.linalg.norm(centers, axis=1)+sizes < .90))
    centers, sizes = centers[valid], sizes[valid]
    if not len(sizes):
        return None
    tolerance = max(1.5/min(radii), .018)
    residual = np.abs(np.linalg.norm(local[:, None, :]-centers[None, :, :], axis=2)-sizes)
    best = np.argmax(np.sum(residual < tolerance, axis=0)-.01*np.median(residual, axis=0))
    inliers = residual[:, best] < tolerance
    for _ in range(3):
        if inliers.sum() < max(36, .50*len(local)):
            return None
        selected = local[inliers]
        design = np.column_stack((2*selected, np.ones(len(selected))))
        if np.linalg.cond(design) > 30:
            return None
        fit = np.linalg.lstsq(design, np.sum(selected*selected, axis=1), rcond=None)[0]
        cc = fit[:2]
        r2 = fit[2]+cc@cc
        if r2 <= 0:
            return None
        size = math.sqrt(r2)
        inliers = np.abs(np.linalg.norm(local-cc, axis=1)-size) < tolerance
    if (inliers.sum() < max(36, .50*len(local)) or not .18 <= size <= .72
            or np.linalg.norm(cc) > .22 or np.linalg.norm(cc)+size >= .90):
        return None
    delta = local[inliers]-cc
    sectors = np.floor((np.arctan2(delta[:, 1], delta[:, 0])+np.pi)/(2*np.pi)*12).astype(int) % 12
    if len(np.unique(sectors)) < 8:
        return None
    ellipse = (tuple((cc*radii) @ rotation.T+center), tuple(np.asarray(axes)*size), float(angle))
    confidence = iris_supported_confidence(gray, ellipse, iris)
    if confidence < .60:
        return None
    return {'ellipse': ellipse, 'edge_support': confidence, 'confidence': confidence,
            'edge_points': boundary[inliers].tolist()}


def detect_reflected_pupil(gray, iris):
    """Recover a pupil whose broad reflections reverse parts of its edge contrast.

    Use current-frame edges of either polarity, not the outline of the remaining
    dark patch. A free ellipse needs distributed boundary support, a dark core,
    an enclosing measured iris, and both ordinary and reversed-contrast arcs.
    Saturated glints, eyelids and unsupported completions cannot supply a pupil.
    """
    if not iris or iris.get('support', 0) < .65:
        return None
    center, axes, angle = iris['ellipse']
    if not np.isfinite([*center, *axes, angle]).all() or min(axes) < 24 or min(axes)/max(axes) < .4:
        return None
    center, radii = np.asarray(center), np.asarray(axes)/2
    theta = math.radians(angle)
    rotation = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    angles = np.linspace(0, 2*np.pi, 120, endpoint=False)
    unit = np.column_stack((np.cos(angles), np.sin(angles)))
    scales = np.linspace(.15, .78, 120)
    points = (unit*radii)[:, None, :]*scales[None, :, None] @ rotation.T + center
    normals = (unit/radii) @ rotation.T
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    smooth = cv2.GaussianBlur(gray, (5, 5), 1)

    def sample(image, xy):
        xy = np.asarray(xy, dtype=np.float32)
        return cv2.remap(image, xy[..., 0], xy[..., 1], cv2.INTER_LINEAR).astype(float)

    inner = sample(smooth, points-3*normals[:, None, :])
    outer = sample(smooth, points+3*normals[:, None, :])
    gx = sample(cv2.Sobel(smooth, cv2.CV_32F, 1, 0), points)
    gy = sample(cv2.Sobel(smooth, cv2.CV_32F, 0, 1), points)
    alignment = np.abs(gx*normals[:, 0, None]+gy*normals[:, 1, None])/np.maximum(1, np.hypot(gx, gy))
    visible = ((points[..., 0] > 4) & (points[..., 0] < gray.shape[1]-4)
               & (points[..., 1] > 4) & (points[..., 1] < gray.shape[0]-4))
    strength = np.abs(outer-inner)+.05*np.hypot(gx, gy)
    strength[(inner >= 235) | (outer >= 235) | (alignment < .8) | ~visible] = -1
    best = np.argmax(strength, axis=1)
    keep = strength[np.arange(len(unit)), best] >= 10
    contrast = (outer-inner)[np.arange(len(unit)), best]
    if np.count_nonzero(keep & (contrast <= -8)) < 6:
        return None
    boundary = points[np.arange(len(unit)), best][keep]
    if len(boundary) < 60:
        return None

    def residual(ellipse):
        c, a, t = ellipse
        t = math.radians(t)
        r = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
        return np.abs(np.linalg.norm((boundary-c) @ r/(np.asarray(a)/2), axis=1)-1)*min(a)/2

    # Fixed seed and bounded hypotheses give deterministic work and stable fits.
    rng = np.random.default_rng(41)
    candidates = [boundary] + [boundary[rng.choice(len(boundary), 8, replace=False)] for _ in range(100)]
    best_count, inliers = 0, None
    for candidate in candidates:
        ellipse = cv2.fitEllipse(candidate.astype(np.float32))
        c, a, t = ellipse
        if (min(a) < 15 or max(a) > max(axes)*.78 or min(a)/max(a) < .45
                or np.linalg.norm(np.asarray(c)-center) > min(axes)*.16):
            continue
        supported = residual(ellipse) < 2.5
        count = np.count_nonzero(supported)
        if count > best_count:
            best_count, inliers = count, supported
    if best_count < max(60, .68*len(boundary)):
        return None
    for _ in range(3):
        if np.count_nonzero(inliers) < max(60, .68*len(boundary)):
            return None
        ellipse = cv2.fitEllipse(boundary[inliers].astype(np.float32))
        inliers = residual(ellipse) < 2.5
    c, a, t = ellipse
    if (np.count_nonzero(inliers) < max(60, .68*len(boundary))
            or min(a) < 15 or not np.isfinite([*c, *a, t]).all()):
        return None
    phi = math.radians(t)
    pr = np.array([[math.cos(phi), -math.sin(phi)], [math.sin(phi), math.cos(phi)]])
    singular = np.linalg.svd(np.diag(1/radii) @ rotation.T @ pr @ np.diag(np.asarray(a)/2), compute_uv=False)
    if not .18 <= singular[0] <= .75 or singular[1]/singular[0] < .75:
        return None
    perimeter = (unit*np.asarray(a)/2) @ pr.T+c
    if np.max(np.linalg.norm((perimeter-center) @ rotation/radii, axis=1)) >= .95:
        return None
    background = float(np.median(sample(smooth, ((unit*radii*.85) @ rotation.T+center)[:, None, :])))
    core = sample(smooth, ((unit*np.asarray(a)*.15) @ pr.T+c)[:, None, :])
    if background-float(np.median(core)) < 12:
        return None
    normal = (unit/(np.asarray(a)/2)) @ pr.T
    normal /= np.linalg.norm(normal, axis=1)[:, None]
    inside = sample(smooth, (perimeter-3*normal)[:, None, :]).ravel()
    outside = sample(smooth, (perimeter+3*normal)[:, None, :]).ravel()
    valid = ((inside < 235) & (outside < 235)
             & (perimeter[:, 0] > 4) & (perimeter[:, 0] < gray.shape[1]-4)
             & (perimeter[:, 1] > 4) & (perimeter[:, 1] < gray.shape[0]-4))
    positive = valid & (outside-inside >= 8)
    negative = valid & (inside-outside >= 8) & (inside > background+max(12, .2*background))
    good = positive | negative
    sectors = np.arange(120)//10
    coverage = sum(np.count_nonzero(good & (sectors == s)) >= 3 for s in range(12))
    if positive.sum() < 24 or negative.sum() < 6 or good.mean() < .65 or coverage < 9:
        return None
    confidence = min(.9, float(iris['support']), float(good.mean()), float(inliers.mean()))
    return {'ellipse': ellipse, 'confidence': confidence, 'edge_support': float(good.mean()),
            'edge_points': boundary[inliers].tolist(), 'source': 'reflection-edge'}


def iris_supported_confidence(gray, pupil, iris, raw_confidence=None):
    """Score current image evidence for a pupil consistent with a reliable iris.

    An iris alone never supplies confidence. Require a dark pupil core, enclosing
    iris, compatible projected shapes, and balanced pupil edges in this frame.
    This is a detector score, not a calibrated probability.
    """
    if (pupil is None or not iris or iris.get('support',0) < .65
            or (raw_confidence is not None and raw_confidence < .25)):
        return 0.
    center, axes, angle = pupil
    icenter, iaxes, iangle = iris['ellipse']
    if (not np.isfinite([*center,*axes,angle,*icenter,*iaxes,iangle]).all()
            or min(axes)<8 or min(iaxes)<=0): return 0.
    def rotation(degrees):
        theta=math.radians(degrees)
        return np.array([[math.cos(theta),-math.sin(theta)],[math.sin(theta),math.cos(theta)]])
    ir, pr = rotation(iangle), rotation(angle)
    radii = np.asarray(iaxes)/2
    transform = np.diag(1/radii) @ ir.T @ pr @ np.diag(np.asarray(axes)/2)
    singular = np.linalg.svd(transform,compute_uv=False)
    if not .15 <= singular[0] <= .75 or singular[1]/singular[0] < .8: return 0.
    angles=np.linspace(0,2*np.pi,72,endpoint=False)
    unit=np.column_stack((np.cos(angles),np.sin(angles)))
    perimeter=(unit*np.asarray(axes)/2) @ pr.T + center
    if np.max(np.linalg.norm((perimeter-icenter) @ ir/radii,axis=1)) > .95: return 0.
    def samples(xy):
        xy=np.asarray(xy,dtype=np.float32)
        return cv2.remap(gray,xy[:,0,None],xy[:,1,None],cv2.INTER_LINEAR).ravel()
    ring=samples((unit*radii*.85) @ ir.T + icenter)
    core=samples((unit*np.asarray(axes)*.2) @ pr.T + center)
    background=float(np.median(ring))
    if background-float(np.median(core)) < 12: return 0.
    # Slightly wider edge samples tolerate modest focus blur, without searching
    # arbitrarily far for an unrelated eyelid or iris edge.
    edge=pupil_edge_support(gray,pupil,min(240,background+max(18,.35*background)),
                            edge_distance=max(3,min(6,min(axes)*.07)))
    if edge < .60: return 0.
    return min(.9,float(iris['support']),edge)


def refine_pupil_with_iris(gray, pupil, iris, contour):
    """Try threshold edges, then recover edges lost to broad reflection gradients."""
    result = _fit_pupil_with_iris(gray, pupil, iris, contour)
    if result is not None:
        return result
    if pupil is None or not iris or iris.get('support', 0) < .65 or contour is None:
        return None
    center, axes, angle = pupil
    icenter, iaxes, iangle = iris['ellipse']
    if (len(contour) < 16 or not np.isfinite([*center,*axes,angle,*icenter,*iaxes,iangle]).all()
            or min(axes) < 8 or min(iaxes) <= max(axes)
            or min(iaxes)/max(iaxes) < .4
            or min(axes)/max(axes) >= min(iaxes)/max(iaxes)-.06):
        return None
    # Search locally around the existing candidate, never at the iris boundary.
    theta = math.radians(iangle)
    rotation = np.array([[math.cos(theta),-math.sin(theta)],
                         [math.sin(theta),math.cos(theta)]])
    radii = np.asarray(iaxes)/2
    angles = np.linspace(0,2*np.pi,96,endpoint=False)
    unit = np.column_stack((np.cos(angles),np.sin(angles)))
    base = max(axes)/max(iaxes)
    scales = np.linspace(.7*base,min(.75,1.3*base),70)
    points = np.asarray(center) + ((unit*radii) @ rotation.T)[:,None,:]*scales[None,:,None]
    normals = (unit/radii) @ rotation.T
    normals /= np.linalg.norm(normals,axis=1)[:,None]
    smooth = cv2.GaussianBlur(gray,(5,5),1)
    def sample(xy):
        return cv2.remap(smooth,xy[...,0].astype(np.float32),xy[...,1].astype(np.float32),
                         cv2.INTER_LINEAR).astype(float)
    ring = (unit*radii*.8) @ rotation.T + icenter
    background = float(np.median(sample(ring[:,None,:])))
    bright_limit = min(240,background+max(18,.35*background))
    distance = max(3,min(6,min(axes)*.06))
    inner = sample(points-distance*normals[:,None,:])
    outer = sample(points+distance*normals[:,None,:])
    gradient = outer-inner
    visible = ((points[...,0]>distance+1)&(points[...,0]<gray.shape[1]-distance-1)
               &(points[...,1]>distance+1)&(points[...,1]<gray.shape[0]-distance-1))
    gradient[(inner>=bright_limit)|(outer>=bright_limit)|~visible] = -1
    best = np.argmax(gradient,axis=1)
    keep = gradient[np.arange(len(unit)),best] >= 6
    boundary = points[np.arange(len(unit)),best][keep]
    if len(boundary) < 24:
        return None
    # Reuse the same center/size bounds, balanced arc coverage, and independent
    # pixel support as the contour fit. An iris prior alone cannot earn acceptance.
    result = _fit_pupil_with_iris(gray,pupil,iris,boundary)
    if result is not None:
        result['boundary_source'] = 'grayscale'
    return result


def _fit_pupil_with_iris(gray, pupil, iris, contour):
    """Fit center/scale with the iris axis ratio and angle as a conditional prior.

    Whitening by the iris semiaxes turns a shared-shape pupil into a circle.
    Robust circle consensus excludes glint-cut edges; independent image gradients
    must support the result. Never creates a pupil, raises confidence, or assumes
    the two centers coincide. Return None when the evidence does not justify it.
    """
    if pupil is None or not iris or iris.get('support', 0) < .55 or contour is None:
        return None
    center, axes, angle = pupil
    icenter, iaxes, iangle = iris['ellipse']
    if (not np.isfinite([*center, *axes, angle, *icenter, *iaxes, iangle]).all()
            or min(axes) < 8 or min(iaxes) <= max(axes)):
        return None
    ratio, iratio = min(axes)/max(axes), min(iaxes)/max(iaxes)
    # Correct narrowing; leave already matching or rounder pupil fits untouched.
    if iratio < .4 or ratio >= iratio-.06:
        return None
    points = np.asarray(contour, dtype=float).reshape(-1, 2)
    points = np.unique(points, axis=0)
    if len(points) < 16 or not np.isfinite(points).all():
        return None
    if len(points) > 120:
        points = points[np.linspace(0,len(points)-1,120).astype(int)]
    theta = math.radians(iangle)
    rotation = np.array([[math.cos(theta), -math.sin(theta)],
                         [math.sin(theta), math.cos(theta)]])
    radii = np.asarray(iaxes)/2
    angles = np.linspace(0,2*np.pi,72,endpoint=False)
    ring = (np.column_stack((np.cos(angles),np.sin(angles)))*radii*.8) @ rotation.T + icenter
    ring = ring.astype(np.float32)
    background = float(np.median(cv2.remap(gray,ring[:,0,None],ring[:,1,None],cv2.INTER_LINEAR)))
    bright_limit = min(240,background+max(18,.35*background))
    # Reject contour segments bordering reflections, including unsaturated halos.
    glints = cv2.dilate((gray >= bright_limit).astype(np.uint8),np.ones((5,5),np.uint8))
    pixel = np.rint(points).astype(int)
    inside = ((pixel[:,0]>=0)&(pixel[:,0]<gray.shape[1])&(pixel[:,1]>=0)&(pixel[:,1]<gray.shape[0]))
    points,pixel = points[inside],pixel[inside]
    points = points[glints[pixel[:,1],pixel[:,0]] == 0]
    if len(points) < 16: return None
    local = (points-icenter) @ rotation / radii
    # Deterministic, bounded three-point hypotheses avoid frame-to-frame randomness.
    ids = np.linspace(0,len(local)-1,min(16,len(local))).astype(int)
    triples = np.array(list(combinations(ids,3)))
    a, b, c = (local[triples[:,i]] for i in range(3))
    u, v = b-a, c-a
    d = 2*(u[:,0]*v[:,1]-u[:,1]*v[:,0])
    valid = np.abs(d) > 1e-5
    a,u,v,d = (x[valid] for x in (a,u,v,d))
    if not len(d): return None
    uu,vv = np.sum(u*u,axis=1),np.sum(v*v,axis=1)
    centers = a + np.column_stack((uu*v[:,1]-vv*u[:,1], u[:,0]*vv-v[:,0]*uu))/d[:,None]
    scales = np.linalg.norm(centers-a,axis=1)
    world_centers = (centers*radii) @ rotation.T + icenter
    base_scale = max(axes)/max(iaxes)
    valid = ((scales >= base_scale*.8) & (scales <= min(.75,base_scale*1.25))
             & (np.linalg.norm(world_centers-center,axis=1) <= .3*min(axes)))
    centers,scales = centers[valid],scales[valid]
    if not len(scales): return None
    residual = np.abs(np.linalg.norm(local[:,None,:]-centers[None,:,:],axis=2)-scales)
    tolerance = max(1.5/min(radii), .04*base_scale)
    counts = np.sum(residual < tolerance,axis=0)
    best = np.argmax(counts - .01*np.median(residual,axis=0))
    inliers = residual[:,best] < tolerance
    for _ in range(3):
        if np.count_nonzero(inliers) < max(12,.55*len(local)): return None
        selected = local[inliers]
        design = np.column_stack((2*selected,np.ones(len(selected))))
        if np.linalg.cond(design) > 30: return None
        fit = np.linalg.lstsq(design,np.sum(selected*selected,axis=1),rcond=None)[0]
        cc = fit[:2]
        r2 = fit[2]+cc@cc
        if r2 <= 0: return None
        scale = math.sqrt(r2)
        inliers = np.abs(np.linalg.norm(local-cc,axis=1)-scale) < tolerance
    if np.count_nonzero(inliers) < max(12,.55*len(local)): return None
    delta = local[inliers]-cc
    arc = np.arctan2(delta[:,1],delta[:,0])
    if len(np.unique(np.floor((arc+np.pi)/(2*np.pi)*12).astype(int))) < 8: return None
    corrected_center = (cc*radii) @ rotation.T + icenter
    corrected_axes = np.asarray(iaxes)*scale
    if (not .8*base_scale <= scale <= min(.75,1.25*base_scale)
            or np.linalg.norm(corrected_center-center) > .3*min(axes)
            or min(corrected_axes) > 1.65*min(axes)
            or np.linalg.norm(cc)+scale > .95): return None
    corrected = (tuple(corrected_center),tuple(corrected_axes),float(iangle))
    support = pupil_edge_support(gray,corrected,bright_limit)
    if support < .55 or support < pupil_edge_support(gray,pupil,bright_limit)-.05:
        return None
    return {'ellipse': corrected, 'edge_support': support,
            'contour_support': float(np.mean(inliers))}


class DetectionLatch:
    """Hysteresis suppresses threshold chatter; prolonged failures still release."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.active = False
        self.last_good = None

    def update(self, confidence, candidate, threshold, now):
        if self.last_good is not None and not 0 <= now - self.last_good <= .25:
            self.reset()
        limit = max(.2, threshold - .08) if self.active else threshold
        good = bool(candidate and confidence >= limit)
        if good:
            self.active = True
            self.last_good = now
        elif self.last_good is None or now - self.last_good > .25:
            self.active = False
        return good

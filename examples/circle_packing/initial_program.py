"""Constructor-based circle packing for n=26 circles."""

import math


def construct_packing():
    """
    Return:
        centers: list of [x, y]
        radii: list of float
    """
    n = 26
    centers = [[0.0, 0.0] for _ in range(n)]

    # Place a circle in the center
    centers[0] = [0.5, 0.5]

    # 8 circles in an inner ring
    for i in range(8):
        angle = 2 * math.pi * i / 8
        centers[i + 1] = [0.5 + 0.3 * math.cos(angle), 0.5 + 0.3 * math.sin(angle)]

    # 16 circles in an outer ring (conservative radius to stay valid)
    for i in range(16):
        angle = 2 * math.pi * i / 16
        centers[i + 9] = [0.5 + 0.38 * math.cos(angle), 0.5 + 0.38 * math.sin(angle)]

    # Clip to keep centers inside the square
    for i in range(n):
        centers[i][0] = max(0.01, min(0.99, centers[i][0]))
        centers[i][1] = max(0.01, min(0.99, centers[i][1]))

    radii = compute_max_radii(centers)
    return centers, radii


def compute_max_radii(centers):
    """Compute maximum non-overlapping radii for fixed centers."""
    n = len(centers)
    radii = [1.0] * n

    for i in range(n):
        x, y = centers[i]
        radii[i] = min(x, y, 1 - x, 1 - y)

    for i in range(n):
        for j in range(i + 1, n):
            dx = centers[i][0] - centers[j][0]
            dy = centers[i][1] - centers[j][1]
            dist = math.sqrt(dx * dx + dy * dy)
            if radii[i] + radii[j] > dist:
                scale = dist / (radii[i] + radii[j])
                radii[i] *= scale
                radii[j] *= scale

    return radii


if __name__ == "__main__":
    c, r = construct_packing()
    print(f"Sum of radii: {sum(r):.6f}")

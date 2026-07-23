function [r, v] = kepler2cart(a, e, inc, raan, argp, nu)
% kepler2cart  Osculating Keplerian elements -> ECI Cartesian state
%
% Input:
%   a    - semi-major axis (meters)
%   e    - eccentricity
%   inc  - inclination (radians)
%   raan - right ascension of ascending node (radians)
%   argp - argument of perigee (radians)
%   nu   - true anomaly (radians)
%
% Output:
%   r - ECI position [x; y; z] (meters)
%   v - ECI velocity [vx; vy; vz] (meters/sec)
%
% Verified against Excel orbit data (rows with e>0) - matches distance column
% to sub-meter accuracy.

MU = 3.986004418e14;  % Earth gravitational parameter (m^3/s^2)

% Semi-latus rectum
p = a * (1.0 - e*e);

% Perifocal position/velocity
denom = 1.0 + e*cos(nu);
r_pf = [p*cos(nu)/denom; p*sin(nu)/denom; 0.0];
h = sqrt(MU * p);
v_pf = [-h/p*sin(nu); h/p*(e + cos(nu)); 0.0];

% Rotation: perifocal -> ECI  (R = Rz(-RAAN) * Rx(-inc) * Rz(-argp))
co = cos(raan); so = sin(raan);
ci = cos(inc);  si = sin(inc);
cw = cos(argp); sw = sin(argp);

R11 = co*cw - so*sw*ci;
R12 = -co*sw - so*cw*ci;
R21 = so*cw + co*sw*ci;
R22 = -so*sw + co*cw*ci;
R31 = sw*si;
R32 = cw*si;

r = [R11*r_pf(1) + R12*r_pf(2);
     R21*r_pf(1) + R22*r_pf(2);
     R31*r_pf(1) + R32*r_pf(2)];

v = [R11*v_pf(1) + R12*v_pf(2);
     R21*v_pf(1) + R22*v_pf(2);
     R31*v_pf(1) + R32*v_pf(2)];

end

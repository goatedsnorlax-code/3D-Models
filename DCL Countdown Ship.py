#
# Run in Autodesk Fusion
# 1. Create a new part (empty)
# 2. Click on Utilities -> Add-ins -> Scripts and Add-ins    (Shift+S)
# 3. "+" -> Create Scripts or Add-in
# 4. Create new (name it, choose Python)
# 5. Save and then find it in the list to open the containing folder
# 6. Edit the pre-generated python file - replace with this file
# 7. Save python file and click the "Run" button in Fusion
# 8. wait ... it can take 30-90 seconds
#

import adsk.core, adsk.fusion, adsk.cam, math, os, traceback
from itertools import permutations


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox('No active Fusion design. Start a new design first, then run this script.')
            return

        root = design.rootComponent
        userParams = design.userParameters

        # The 3MF exporter follows the document's units. Left on cm or inch it
        # writes a file the slicer reads at the wrong scale.
        design.fusionUnitsManager.distanceDisplayUnits = \
            adsk.fusion.DistanceUnits.MillimeterDistanceUnits

        def require(condition, message):
            if not condition:
                raise RuntimeError(message)

        def drop(entity, what):
            """deleteMe() returns False rather than raising when Fusion declines.
            Unchecked, scratch geometry silently survives into the export."""
            require(entity.deleteMe(),
                    'Fusion would not delete {} -- it would have been left in the '
                    'model and exported as a stray part.'.format(what))

        def mm(v):
            """Fusion's internal unit is cm; every number in this script is mm."""
            return v / 10.0

        def P(x, y):
            return adsk.core.Point3D.create(mm(x), mm(y), 0)

        # ---------------------------------------------------------------- cleanup
        for s in list(root.sketches):
            if s.name.startswith(('Hull_', 'Deck_', 'Cut_', 'Cube_', 'Stack_',
                                  'Boat_', 'Mick_', 'Probe_')):
                s.deleteMe()
        for b in list(root.bRepBodies):
            if b.name.startswith(('Hull', 'Body', 'Cube', 'Stack', 'Probe')):
                b.deleteMe()
        for p in list(root.constructionPlanes):
            if p.name.startswith(('Deck_P', 'Cut_P', 'Boat_P', 'Mick_P')):
                p.deleteMe()

        def set_param(name, expr, units, comment=''):
            existing = userParams.itemByName(name)
            if existing:
                # deleteMe() returns False rather than raising when another
                # parameter's expression still references this one.
                if not existing.deleteMe():
                    try:
                        existing.unit = units
                    except:
                        pass
                    existing.expression = expr
                    if comment:
                        existing.comment = comment
                    return existing
            return userParams.add(name, adsk.core.ValueInput.createByString(expr), units, comment)

        extrudes = root.features.extrudeFeatures
        lofts = root.features.loftFeatures
        combines = root.features.combineFeatures
        moves = root.features.moveFeatures

        # ------------------------------------------------ symmetric-extrude probe
        # setDistanceExtent(True, d) may apply d per side or as the total, and
        # getting it wrong doubled every symmetric cut in this file -- the cube
        # slots came out 27 mm deep instead of 18. Measure it rather than assume.
        probeSk = root.sketches.add(root.xYConstructionPlane)
        probeSk.name = 'Probe_Symmetric'
        probeLines = probeSk.sketchCurves.sketchLines
        pp = probeSk.sketchPoints
        pa = pp.add(P(300.0, 0.0))
        pb = pp.add(P(302.0, 0.0))
        pc = pp.add(P(302.0, 2.0))
        pd = pp.add(P(300.0, 2.0))
        probeLines.addByTwoPoints(pa, pb)
        probeLines.addByTwoPoints(pb, pc)
        probeLines.addByTwoPoints(pc, pd)
        probeLines.addByTwoPoints(pd, pa)
        require(probeSk.profiles.count == 1, 'Symmetric-extrude probe sketch did not close.')
        probeIn = extrudes.createInput(probeSk.profiles.item(0),
                                       adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        probeIn.setDistanceExtent(True, adsk.core.ValueInput.createByString('10 mm'))
        probeBody = extrudes.add(probeIn).bodies.item(0)
        probeBody.name = 'Probe_Body'
        probeSpan = (probeBody.boundingBox.maxPoint.z - probeBody.boundingBox.minPoint.z) * 10.0
        SYMMETRIC_PER_SIDE = probeSpan > 15.0
        drop(probeBody, 'the symmetric-extrude probe body')
        drop(probeSk, 'the symmetric-extrude probe sketch')

        def symmetric_value(totalDepth):
            """What to hand setDistanceExtent so the cut is totalDepth overall."""
            return totalDepth / 2.0 if SYMMETRIC_PER_SIDE else totalDepth

        # ------------------------------------------------------------ parameters
        set_param('hullLength', '152.4 mm', 'mm', 'Overall bow-to-stern length at deck level')
        set_param('hullBeam', '45 mm', 'mm', 'Hull width, port to starboard')
        set_param('hullHeight', '27 mm', 'mm', 'Hull band -- also hosts the spare cube pocket')
        set_param('bowTaperLength', '46 mm', 'mm', 'Length over which the bow narrows')
        set_param('bowTipWidth', '14 mm', 'mm', 'Bow tip width at deck level')
        set_param('bowTipWidthKeel', '8 mm', 'mm', 'Bow tip width at the keel -- finer entry')
        set_param('bowRake', '12 mm', 'mm', 'How far the keel bow sits aft of the deck bow')
        set_param('bowStemBulge', '2 mm', 'mm', 'Forward push at mid-height, making the stem convex')
        set_param('sternTaperLength', '34 mm', 'mm', 'Length over which the stern narrows')
        set_param('sternTipWidth', '32 mm', 'mm', 'Hull transom width -- frames the spare cube')
        set_param('keelFillet', '3 mm', 'mm', 'Bottom perimeter round')
        set_param('gunwaleFillet', '1 mm', 'mm', 'Top perimeter round -- small, to leave a recess landing')
        set_param('bodyRecessDepth', '0.4 mm', 'mm', 'Locating recess -- matches what the test print had')
        set_param('bodyRecessGap', '0.1 mm', 'mm', 'Clearance per side')
        set_param('lifeboatLength', '9 mm', 'mm', 'Lifeboat pod fore-aft size')
        set_param('lifeboatHeight', '3.5 mm', 'mm', 'Lifeboat pod vertical size')
        set_param('lifeboatProud', '1.5 mm', 'mm', 'How far each pod stands off the hull')
        set_param('lifeboatPitch', '12 mm', 'mm', 'Spacing between lifeboats')
        set_param('lifeboatZ', '23.5 mm', 'mm', 'Lifeboat row height -- as high as the gunwale allows')
        set_param('floorHeight', '6 mm', 'mm', 'One deck -- every main floor is this tall')
        set_param('promenadeHeight', '3 mm', 'mm', 'Thin deck at the hull joint; the cubes sit on it')
        set_param('sternStepPerFloor', '4.5 mm', 'mm', 'Aft terrace step at each floor')
        set_param('bowStepPerFloor', '4 mm', 'mm', 'Forward terrace step at each floor')
        set_param('cubeSize', '20 mm', 'mm', 'Countdown cube edge length')
        set_param('cubeCount', '3', '', 'Number of cubes displayed at once')
        set_param('cubeClearance', '0.6 mm', 'mm', 'Slack so a cube slides in and out freely')
        set_param('slotDepth', '16 mm', 'mm', 'Display slot depth -- cube stands cubeSize minus this proud')
        set_param('cubeEdgeFillet', '1 mm', 'mm', 'Cube edge break')
        set_param('dividerThickness', '2 mm', 'mm', 'Wall between adjacent cube slots')
        set_param('slotCeiling', '2.8 mm', 'mm', 'Material above the display slots')
        set_param('spareFloor', '3 mm', 'mm', 'Hull material below the spare pocket')
        set_param('spareClearance', '1.2 mm', 'mm', 'Transom pocket slack, total across the cube')
        set_param('boatMaxSag', '1 mm', 'mm', 'Drop a lifeboat where the hull falls away more than this')
        set_param('groovePitch', '3 mm', 'mm', 'Deck-line spacing')
        set_param('digitRecessDepth', '0.6 mm', 'mm', 'Engraved digit depth -- 3 layers at 0.2, holds paint')
        set_param('digitInkHeight', '11 mm', 'mm', 'Height of the digit you actually see -- calibrated per font')
        set_param('hullTextProud', '0.6 mm', 'mm', 'How far the raised lettering stands off the hull')
        set_param('hullTextBandLo', '4.5 mm', 'mm', 'Bottom of the sentiment band, clear of the keel fillet')
        set_param('hullTextBandHi', '20.5 mm', 'mm', 'Top of the sentiment band, clear of the lifeboats')
        set_param('stackBaseLength', '18 mm', 'mm', 'Funnel fore-aft size at the deck')
        set_param('stackBaseWidth', '12 mm', 'mm', 'Funnel athwartships size at the deck')
        set_param('stackTopLength', '15 mm', 'mm', 'Funnel fore-aft size under the cap')
        set_param('stackTopWidth', '10 mm', 'mm', 'Funnel athwartships size under the cap')
        set_param('stackCapLength', '16.5 mm', 'mm', 'Cap fore-aft size -- the lip')
        set_param('stackCapWidth', '11.5 mm', 'mm', 'Cap athwartships size -- the lip')
        set_param('stackBodyHeight', '14 mm', 'mm', 'Red section height')
        set_param('stackCapHeight', '4 mm', 'mm', 'Black cap height -- a flat AMS colour swap')
        set_param('stackRake', '4 mm', 'mm', 'How far the funnel top leans aft of its base')
        set_param('stackSpacing', '22 mm', 'mm', 'Distance between the two funnels')
        set_param('stackCentreX', '-16 mm', 'mm', 'Fore-aft midpoint of the funnel pair')
        set_param('stackPegDiaAft', '4 mm', 'mm', 'Aft locating pin -- larger, so the funnel is keyed')
        set_param('stackPegDiaFwd', '3 mm', 'mm', 'Forward locating pin -- smaller')
        set_param('stackPegSpacing', '10 mm', 'mm', 'Distance between the two pins')
        set_param('stackPegHeight', '3 mm', 'mm', 'Pin height')
        set_param('stackSocketExtra', '1.5 mm', 'mm', 'How far the socket outruns the pin')
        set_param('mickeyHeadDia', '6 mm', 'mm', 'Mickey head diameter on the funnel')
        set_param('mickeyEarDia', '3.4 mm', 'mm', 'Mickey ear diameter')
        set_param('mickeyProud', '0.5 mm', 'mm', 'How far the emblem stands off its local surface')
        set_param('mickeyEarGap', '-0.7 mm', 'mm', 'How far each ear laps over the head; negative is overlap')
        set_param('mickeyEarAngle', '48 deg', 'deg', 'Ear position around the head, from vertical')
        set_param('mickeyHeightFrac', '0.44', '', 'Where the head sits up the red band, 0 to 1')
        set_param('cubeMarkScale', '0.45', '', 'Mickey emblem size on a cube, relative to the funnel one')

        # ------------------------------------------------- numeric seeds (all mm)
        L, B, hullH = 152.4, 45.0, 27.0
        FLOOR, PROM = 6.0, 3.0
        bowTaperLen, bowTipW, bowTipWKeel = 46.0, 14.0, 8.0
        bowRake, stemBulge = 12.0, 2.0
        sternTaperLen, sternTipW = 34.0, 32.0
        keelFillet, gunwaleFillet = 3.0, 1.0
        HULL_BULGE = 2.0              # the arc bulge ship_outline draws the hull with
        recessDepth, recessGap = 0.4, 0.1
        boatLen, boatHt, boatProud, boatPitch, boatZ = 9.0, 3.5, 1.5, 12.0, 23.5
        boatFirstX, boatLastX = -55.0, 45.0
        boatMaxSag = 1.0              # drop a pod if the hull falls away more than this
        boatSinkMargin = 0.6          # bite past the shallowest point the pod covers
        cube, clearance, divider = 20.0, 0.6, 2.0
        slotDepth = 16.0
        cubeN, slotCeiling = 3, 2.8
        cubeEdgeFillet = 1.0
        grooveDepth, grooveHeight, groovePitch = 1.0, 1.2, 3.0
        spareFloor = 3.0
        spareClearance = 1.2          # total, so 0.6 a side -- the transom pocket is
                                      # half again deeper than a display slot, so its
                                      # walls bow in further and 0.6 total seized up
        spareGripDia = 6.0            # finger notch in each pocket side wall
        spareGripDepth = 8.0          # how far forward the notches run
        spareDepth = cube + spareClearance
        stackBaseL, stackBaseW = 18.0, 12.0
        stackTopL, stackTopW = 15.0, 10.0
        stackCapL, stackCapW = 16.5, 11.5
        stackBodyH, stackCapH, stackRake = 14.0, 4.0, 4.0
        stackSpacing, stackCentreX = 22.0, -16.0
        pegDiaAft, pegDiaFwd, pegSpacing, pegH = 4.0, 3.0, 10.0, 3.0
        socketExtra = 1.5             # socket depth past the peg; 0.5 left it proud
        socketRelief = 1.2            # extra diameter at the socket mouth
        socketReliefDepth = 0.8       # depth of that counterbore
        mickHead, mickEar, mickProud, mickFrac = 6.0, 3.4, 0.5, 0.44
        mickEarGap = -0.7             # negative: how far the ear laps over the head
        mickEarAngle = 48.0           # degrees from vertical
        mickSinkMargin = 0.5          # spare depth under the shallowest covered point

        # The funnel emblem's ear offset. Defined here rather than down in the
        # funnel section because the cube marks reuse it, scaled.
        earOffset = (mickHead + mickEar) / 2.0 + mickEarGap
        EAR_SIN = math.sin(math.radians(mickEarAngle))
        EAR_COS = math.cos(math.radians(mickEarAngle))
        require(earOffset < (mickHead + mickEar) / 2.0 - 0.3,
                'Ears sit {:.2f} mm from the head centre against {:.2f} mm of combined '
                'radius. They need real overlap or they read as three loose blobs.'
                .format(earOffset, (mickHead + mickEar) / 2.0))

        # ----------------------------------------------------- digit engraving
        # Fusion matches the family name exactly and rejects anything else, and
        # the spelling varies between Waltograph releases. Put your preferred
        # name first; the resolver tries each in turn and reports what it used.
        FONT_NAME = 'Waltograph UI'
        FONT_ALTERNATES = ['Waltograph', 'waltograph UI', 'WaltographUI',
                           'Waltograph 42', 'Waltograph42']
        FONT_IN_USE = [FONT_NAME]     # set by resolve_font before anything is built
        digitRecess = 0.84            # 2 layers at 0.42 -- deep enough to hold paint
        digitInkHeight = 11.0         # visible glyph height -- calibrated, not guessed
        digitEmSeed = 15.0            # starting em size for the calibration pass
        digitBold = False             # Waltograph has no real bold weight
        digitShiftMark = 2.0          # lift the digit on faces that carry the mark
        digitMarkGap = 0.8            # clear space demanded between digit and mark
        toolOvershoot = 0.5           # how far the cut tool pokes past the face

        MARK_6_AND_9 = True           # Mickey doubles as the 6/9 orientation mark
        markScale = 0.45              # relative to the funnel emblem
        markCentreY = -6.6            # below the face centre

        # ------------------------------------------------ hull sentiment text
        # One string per side. Both share a single scale, so they come out the
        # same size however different their lengths are.
        HULL_TEXT = {'P': "Days 'Til Norway",      # the display side, with the cubes
                     'S': "P&O Cruises - Iona"}   # the reverse, with no countdown
        hullTextSharedScale = True    # False lets each side fill the hull on its own
        hullTextSides = ('S', 'P')    # which hull sides carry it
        hullTextProud = 0.6           # how far the lettering stands off the hull
        hullTextBite = 1.5            # deep enough to swallow the bow's vertical twist
        hullTextSeedEm = 20.0         # starting em size for the fit pass
        hullTextMargin = 3.0          # clear arc length left at each end of the run
        hullTextMaxTwist = 1.2        # mm the surface may shift across the band
        hullTextMaxTangent = 22.0     # degrees the surface may turn from fore-aft
        hullTextMinGlyphs = 4         # a fully joined script would defeat the curving
        hullTextMinStroke = 0.45      # mm; about one extrusion width -- a hard floor
        hullTextWarnStroke = 0.84     # two Bambu outer walls at 0.42, not 2 x 0.40
        hullTextBandLo = 4.5
        hullTextBandHi = 20.5

        cubeProud = cube - slotDepth

        bowX, sternX = L / 2.0, -L / 2.0
        bowTaperStart = bowX - bowTaperLen
        sternTaperEnd = sternX + sternTaperLen

        MAIN_INSET, PROM_INSET = 4.0, 2.0
        STERN_STEP, BOW_STEP = 4.5, 4.0
        aft0, fwd0 = -72.0, 58.0
        FWD_MIN = bowTaperStart + 4.0

        def aft(n):
            return aft0 + n * STERN_STEP

        def fwd(n):
            return max(fwd0 - n * BOW_STEP, FWD_MIN)

        DIAG = math.sqrt(0.5)
        AXIS_NAMES = ('x', 'y', 'z')

        # ------------------------------------------------------------- outline fn
        def half_width_at(x, inset):
            """Half-beam of the hull form at station x, reduced by inset.

            A straight-line model of each taper. Good enough to lay out the
            outlines themselves; hull_surface_y below is the truthful one, for
            anything that has to sit ON the finished surface."""
            full = max(B / 2.0 - inset, 1.0)
            if x <= sternTaperEnd:
                t = (x - sternX) / (sternTaperEnd - sternX)
                tip = max(sternTipW / 2.0 - inset, 1.0)
                return max(tip + (full - tip) * t, 1.0)
            if x >= bowTaperStart:
                t = (x - bowTaperStart) / (bowX - bowTaperStart)
                tip = max(bowTipW / 2.0 - inset, 1.0)
                return max(full + (tip - full) * t, 1.0)
            return full

        def ship_outline(sketch, xAft, xFwd, inset, bulge=1.5, fwdHalfOverride=None):
            """Ship plan shape: tapered stern to a flat transom, parallel midship
            sides, tapered bow to a blunt forward cut.

            Corner points are created up front and handed to both curves meeting
            there. Never read endpoints back off a curve -- addByThreePoints stores
            arcs counter-clockwise, so a clockwise arc returns start and end
            swapped and a chain built that way connects the wrong corners."""
            full = max(B / 2.0 - inset, 1.0)
            aftHalf = half_width_at(xAft, inset)
            fwdHalf = fwdHalfOverride if fwdHalfOverride is not None else half_width_at(xFwd, inset)
            hasStern = xAft < sternTaperEnd - 2.0
            hasBow = xFwd > bowTaperStart + 2.0

            require(xAft < xFwd - 10.0,
                    'Outline "{}": aft {:.1f} and forward {:.1f} stations are too close.'
                    .format(sketch.name, xAft, xFwd))
            require(full > 2.0,
                    'Outline "{}": half-beam {:.1f} too small -- inset {:.1f} is too large.'
                    .format(sketch.name, full, inset))
            require(aftHalf > 1.5 and fwdHalf > 1.5,
                    'Outline "{}": end half-widths {:.1f}/{:.1f} collapse to nothing.'
                    .format(sketch.name, aftHalf, fwdHalf))

            sp = sketch.sketchPoints
            aftStbd = sp.add(P(xAft, aftHalf))
            aftPort = sp.add(P(xAft, -aftHalf))
            if hasStern:
                sternEndStbd = sp.add(P(sternTaperEnd, full))
                sternEndPort = sp.add(P(sternTaperEnd, -full))
            else:
                sternEndStbd, sternEndPort = aftStbd, aftPort
            if hasBow:
                bowStartStbd = sp.add(P(bowTaperStart, full))
                bowStartPort = sp.add(P(bowTaperStart, -full))
                fwdStbd = sp.add(P(xFwd, fwdHalf))
                fwdPort = sp.add(P(xFwd, -fwdHalf))
            else:
                bowStartStbd = sp.add(P(xFwd, fwdHalf))
                bowStartPort = sp.add(P(xFwd, -fwdHalf))
                fwdStbd, fwdPort = bowStartStbd, bowStartPort

            lines = sketch.sketchCurves.sketchLines
            arcs = sketch.sketchCurves.sketchArcs

            transom = lines.addByTwoPoints(aftPort, aftStbd)
            if hasStern:
                mx = (xAft + sternTaperEnd) / 2.0
                my = (aftHalf + full) / 2.0 + bulge
                arcs.addByThreePoints(aftStbd, P(mx, my), sternEndStbd)
            sideStbd = lines.addByTwoPoints(sternEndStbd, bowStartStbd)
            if hasBow:
                mx = (bowTaperStart + xFwd) / 2.0
                my = (full + fwdHalf) / 2.0 + bulge
                arcs.addByThreePoints(bowStartStbd, P(mx, my), fwdStbd)
            fwdCap = lines.addByTwoPoints(fwdStbd, fwdPort)
            if hasBow:
                mx = (bowTaperStart + xFwd) / 2.0
                my = -((full + fwdHalf) / 2.0 + bulge)
                arcs.addByThreePoints(fwdPort, P(mx, my), bowStartPort)
            sidePort = lines.addByTwoPoints(bowStartPort, sternEndPort)
            if hasStern:
                mx = (xAft + sternTaperEnd) / 2.0
                my = -((aftHalf + full) / 2.0 + bulge)
                arcs.addByThreePoints(sternEndPort, P(mx, my), aftPort)

            gc = sketch.geometricConstraints
            gc.addVertical(transom)
            gc.addVertical(fwdCap)
            gc.addHorizontal(sideStbd)
            gc.addHorizontal(sidePort)

            require(sketch.profiles.count > 0,
                    'Sketch "{}" has no closed profile after building the outline.'.format(sketch.name))

        planeCache = {}

        def plane_at(z):
            key = round(z, 4)
            if key not in planeCache:
                pi = root.constructionPlanes.createInput()
                pi.setByOffset(root.xYConstructionPlane,
                               adsk.core.ValueInput.createByString('{} mm'.format(z)))
                p = root.constructionPlanes.add(pi)
                p.name = 'Deck_P_{}'.format(key).replace('.', '_').replace('-', 'n')
                p.isLightBulbOn = False
                planeCache[key] = p
            return planeCache[key]

        def axis_component(point, axis):
            return {'x': point.x, 'y': point.y, 'z': point.z}[axis]

        def sketch_axis_map(sk):
            """Measure which global axes this sketch's local X and Y actually track.

            Fusion's construction-plane orientations are not worth assuming: getting
            the YZ plane's mapping backwards silently rotates a pocket 90 degrees."""
            o = sk.sketchToModelSpace(adsk.core.Point3D.create(0.0, 0.0, 0.0))
            pu = sk.sketchToModelSpace(adsk.core.Point3D.create(1.0, 0.0, 0.0))
            pv = sk.sketchToModelSpace(adsk.core.Point3D.create(0.0, 1.0, 0.0))
            uVec = (pu.x - o.x, pu.y - o.y, pu.z - o.z)
            vVec = (pv.x - o.x, pv.y - o.y, pv.z - o.z)

            def dominant(vec):
                i = max(range(3), key=lambda k: abs(vec[k]))
                return AXIS_NAMES[i], (1.0 if vec[i] >= 0 else -1.0)

            return (o,) + dominant(uVec) + dominant(vVec)

        def offset_plane(name, basePlane, offsetMM):
            pi = root.constructionPlanes.createInput()
            pi.setByOffset(basePlane, adsk.core.ValueInput.createByString('{} mm'.format(offsetMM)))
            plane = root.constructionPlanes.add(pi)
            plane.name = name
            plane.isLightBulbOn = False
            return plane

        def local_mapper(sk, axes):
            o, uAxis, uSign, vAxis, vSign = sketch_axis_map(sk)
            require(set([uAxis, vAxis]) == set(axes),
                    'Sketch "{}" lies along global {}/{}, but its geometry is given '
                    'in {}/{}.'.format(sk.name, uAxis, vAxis, axes[0], axes[1]))

            def to_local(gA, gB):
                vals = {axes[0]: mm(gA), axes[1]: mm(gB)}
                u = (vals[uAxis] - axis_component(o, uAxis)) / uSign
                v = (vals[vAxis] - axis_component(o, vAxis)) / vSign
                return adsk.core.Point3D.create(u, v, 0)
            return to_local

        def all_profiles(sk):
            coll = adsk.core.ObjectCollection.create()
            for i in range(sk.profiles.count):
                coll.add(sk.profiles.item(i))
            return coll

        toolSerial = [0]

        def label_tool_bodies(feature):
            """Tag the cut tools so a failed run leaves identifiable debris that
            the cleanup at the top of the script sweeps up.

            The tools are tracked by FEATURE, never by name. Renaming a body is
            not a timeline operation, so the name does not survive a recompute --
            which is exactly what broke when the calibration bodies were deleted
            one at a time by name."""
            for i in range(feature.bodies.count):
                toolSerial[0] += 1
                feature.bodies.item(i).name = 'Cube_Tool_{}'.format(toolSerial[0])
            return feature

        def tool_bodies(feats):
            """Live bodies of the given features, re-read on every call."""
            out = []
            for f in feats:
                require(f.bodies.count > 0, 'A cut tool feature produced no bodies.')
                for i in range(f.bodies.count):
                    out.append(f.bodies.item(i))
            return out

        def bodies_extent(feats):
            """Combined bounding box of those features' bodies, in mm."""
            lo = [1.0e9, 1.0e9, 1.0e9]
            hi = [-1.0e9, -1.0e9, -1.0e9]
            bodies = tool_bodies(feats)
            require(len(bodies) > 0, 'Nothing to measure.')
            for b in bodies:
                bb = b.boundingBox
                spans = ((bb.minPoint.x, bb.maxPoint.x),
                         (bb.minPoint.y, bb.maxPoint.y),
                         (bb.minPoint.z, bb.maxPoint.z))
                for i, (mn, mx) in enumerate(spans):
                    lo[i] = min(lo[i], mn * 10.0)
                    hi[i] = max(hi[i], mx * 10.0)
            return lo, hi

        def collect(feats):
            coll = adsk.core.ObjectCollection.create()
            for b in tool_bodies(feats):
                coll.add(b)
            return coll

        def move_solids(bodies, matrix):
            coll = adsk.core.ObjectCollection.create()
            for b in bodies:
                coll.add(b)
            if hasattr(moves, 'createInput2'):
                mi = moves.createInput2(coll)
                mi.defineAsFreeMove(matrix)
            else:
                mi = moves.createInput(coll, matrix)
            moves.add(mi)

        def move_by_matrix(feats, matrix):
            move_solids(tool_bodies(feats), matrix)

        def translate(feats, dx, dy):
            if abs(dx) < 1.0e-6 and abs(dy) < 1.0e-6:
                return
            matrix = adsk.core.Matrix3D.create()
            matrix.translation = adsk.core.Vector3D.create(mm(dx), mm(dy), 0.0)
            move_by_matrix(feats, matrix)

        def text_tool(sketchName, text, emHeight, depth):
            """Text prism standing on the world XY plane.

            Fusion's MiddleVerticalAlignment anchors a single line near the
            bottom of its box rather than centring it, which is what dropped the
            digits to the bottom of the cube. So the box is used only to stop
            wrapping; the glyph gets centred afterwards by measuring where the
            ink actually landed."""
            sk = root.sketches.add(root.xYConstructionPlane)
            sk.name = sketchName
            boxW = emHeight * len(text) * 1.6 + 10.0
            boxH = emHeight * 3.0
            inp = sk.sketchTexts.createInput2(text, mm(emHeight))
            inp.fontName = FONT_IN_USE[0]
            if digitBold:
                inp.textStyle = adsk.fusion.TextStyles.TextStyleBold
            inp.setAsMultiLine(
                P(-boxW / 2.0, -boxH / 2.0), P(boxW / 2.0, boxH / 2.0),
                adsk.core.HorizontalAlignments.CenterHorizontalAlignment,
                adsk.core.VerticalAlignments.MiddleVerticalAlignment,
                0.0)
            try:
                txt = sk.sketchTexts.add(inp)
            except:
                raise RuntimeError(
                    'Fusion would not create text in the font "{}", although the '
                    'resolver accepted that name earlier in this run.'
                    .format(FONT_IN_USE[0]))
            op = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
            try:
                ei = extrudes.createInput(txt, op)
            except:
                coll = adsk.core.ObjectCollection.create()
                coll.add(txt)
                ei = extrudes.createInput(coll, op)
            ei.setDistanceExtent(False, adsk.core.ValueInput.createByString(
                '{} mm'.format(depth)))
            feat = extrudes.add(ei)
            require(feat.bodies.count > 0,
                    'Text "{}" produced no solid -- the glyph outlines in "{}" are '
                    'probably self-intersecting.'.format(text, FONT_IN_USE[0]))
            return label_tool_bodies(feat), sk

        def font_files_on_disk(needle):
            """Where the font actually lives, which says whether Fusion could
            ever see it. A file only under ~/Library/Fonts is installed for this
            user; Fusion does not always pick those up."""
            hits = []
            for folder in (os.path.expanduser('~/Library/Fonts'),
                           '/Library/Fonts', '/System/Library/Fonts',
                           os.path.join(os.environ.get('WINDIR', ''), 'Fonts')):
                try:
                    for f in sorted(os.listdir(folder)):
                        if needle.lower() in f.lower():
                            hits.append(os.path.join(folder, f))
                except:
                    pass
            return hits

        def resolve_font():
            """Find a family name Fusion will actually accept, before a thousand
            features depend on it. Fusion raises on add(), not on setting
            fontName, so the only honest test is to create one and throw it away."""
            tried = []
            for name in [FONT_NAME] + FONT_ALTERNATES:
                if name in tried:
                    continue
                tried.append(name)
                sk = root.sketches.add(root.xYConstructionPlane)
                sk.name = 'Probe_Font'
                try:
                    inp = sk.sketchTexts.createInput2('0', mm(10.0))
                    inp.fontName = name
                    inp.setAsMultiLine(
                        P(-20.0, -20.0), P(20.0, 20.0),
                        adsk.core.HorizontalAlignments.CenterHorizontalAlignment,
                        adsk.core.VerticalAlignments.MiddleVerticalAlignment, 0.0)
                    sk.sketchTexts.add(inp)
                    sk.deleteMe()
                    FONT_IN_USE[0] = name
                    return name
                except:
                    try:
                        sk.deleteMe()
                    except:
                        pass
            found = font_files_on_disk('walto')
            raise RuntimeError(
                'Fusion rejected every font name tried: {}.\n\n'
                'Matching font files on this machine:\n  {}\n\n'
                'Open Sketch > Create > Text in Fusion and read the exact family '
                'name out of the Font dropdown, then set FONT_NAME to it. If it is '
                'not in that dropdown at all, Fusion cannot see the font: '
                'reinstall it in Font Book with "Install for: All Users", then '
                'restart Fusion -- the font list is only read at launch.'
                .format(', '.join('"{}"'.format(t) for t in tried),
                        '\n  '.join(found) if found else
                        '(none found -- the font is not installed)'))

        fontInUse = resolve_font()

        # ------------------------------------------------------------------- hull
        hullSections = [
            (0.0,         bowX - bowRake,                   bowTipWKeel / 2.0),
            (hullH / 2.0, bowX - bowRake / 2.0 + stemBulge, (bowTipWKeel + bowTipW) / 4.0),
            (hullH,       bowX,                             bowTipW / 2.0),
        ]
        stemAngles = []
        for i in range(1, len(hullSections)):
            dz = hullSections[i][0] - hullSections[i - 1][0]
            dx = hullSections[i][1] - hullSections[i - 1][1]
            require(dx > 0, 'Hull bow stations must increase with height.')
            stemAngles.append(math.degrees(math.atan2(dx, dz)))
        maxStem = max(stemAngles)
        require(maxStem < 45.0,
                'Stem leans {:.0f} deg from vertical -- past self-support keel-down.'.format(maxStem))

        def arc_y(x1, y1, xm, ym, x2, y2, x):
            """y on the circular arc through three points -- what
            addByThreePoints actually draws.

            half_width_at models each taper as a straight line, which is out by
            up to 2 mm against the real arc. Flat lettering never noticed
            because it sat in the flat midship zone; curved lettering and the
            lifeboat pods both sit on the taper, where it matters."""
            d = 2.0 * (x1 * (ym - y2) + xm * (y2 - y1) + x2 * (y1 - ym))
            if abs(d) < 1.0e-9:
                return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
            q1, qm, q2 = x1 * x1 + y1 * y1, xm * xm + ym * ym, x2 * x2 + y2 * y2
            ux = (q1 * (ym - y2) + qm * (y2 - y1) + q2 * (y1 - ym)) / d
            uy = (q1 * (x2 - xm) + qm * (x1 - x2) + q2 * (xm - x1)) / d
            R = math.hypot(x1 - ux, y1 - uy)
            s = 1.0 if ym >= uy else -1.0
            return uy + s * math.sqrt(max(R * R - (x - ux) ** 2, 0.0))

        def section_half(xFwd, fwdHalf, x):
            """Half-beam of one hull loft section, or None past its bow tip."""
            if x <= sternTaperEnd:
                return arc_y(sternX, sternTipW / 2.0,
                             (sternX + sternTaperEnd) / 2.0,
                             (sternTipW / 2.0 + B / 2.0) / 2.0 + HULL_BULGE,
                             sternTaperEnd, B / 2.0, x)
            if x >= bowTaperStart:
                if x > xFwd:
                    return None
                return arc_y(bowTaperStart, B / 2.0,
                             (bowTaperStart + xFwd) / 2.0,
                             (B / 2.0 + fwdHalf) / 2.0 + HULL_BULGE,
                             xFwd, fwdHalf, x)
            return B / 2.0

        def hull_surface_y(x, z):
            """True half-beam of the lofted hull at station x, height z.

            The stern taper is identical in all three sections, so that end is a
            vertical surface. The bow rakes, so its half-beam shifts with height
            -- which is what limits how far forward flat glyphs can sit."""
            for i in range(len(hullSections) - 1):
                z0, xf0, h0 = hullSections[i]
                z1, xf1, h1 = hullSections[i + 1]
                if z0 <= z <= z1:
                    a = section_half(xf0, h0, x)
                    b = section_half(xf1, h1, x)
                    if a is None or b is None:
                        return None
                    return a + (b - a) * (z - z0) / (z1 - z0)
            return None

        hullLoftInput = lofts.createInput(adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        for idx, (z, xFwd, halfTip) in enumerate(hullSections):
            sk = root.sketches.add(plane_at(z) if z > 0 else root.xYConstructionPlane)
            sk.name = 'Hull_Plan_{}'.format(idx)
            ship_outline(sk, sternX, xFwd, 0.0, bulge=HULL_BULGE, fwdHalfOverride=halfTip)
            hullLoftInput.loftSections.add(sk.profiles.item(0))
        hullLoftInput.isSolid = True
        hullBody = lofts.add(hullLoftInput).bodies.item(0)
        hullBody.name = 'Hull'

        fillets = root.features.filletFeatures

        def fillet_edges(edgeList, expression, label):
            require(len(edgeList) > 0, 'Found no {} edges to fillet.'.format(label))
            coll = adsk.core.ObjectCollection.create()
            for e in edgeList:
                coll.add(e)
            fi = fillets.createInput()
            fi.edgeSetInputs.addConstantRadiusEdgeSet(
                coll, adsk.core.ValueInput.createByString(expression), False)
            fillets.add(fi)

        def ring_edges(body, targetZ, tol=0.02):
            out = []
            for edge in body.edges:
                p1 = edge.startVertex.geometry
                p2 = edge.endVertex.geometry
                if abs(p1.z - targetZ) <= tol and abs(p2.z - targetZ) <= tol:
                    out.append(edge)
            return out

        fillet_edges(ring_edges(hullBody, 0.0), 'keelFillet', 'keel')
        fillet_edges(ring_edges(hullBody, mm(hullH)), 'gunwaleFillet', 'gunwale')

        # --------------------------------------------- locating recess in the deck
        for station in (aft0 - recessGap, 0.0, fwd0 + recessGap):
            deckHalf = half_width_at(station, 0.0) - gunwaleFillet
            recessHalf = half_width_at(station, PROM_INSET - recessGap)
            require(recessHalf < deckHalf - 0.3,
                    'At x={:.1f} the recess half-width {:.2f} mm leaves no landing inside '
                    'the filleted deck at {:.2f} mm.'.format(station, recessHalf, deckHalf))

        recessSk = root.sketches.add(plane_at(hullH - recessDepth / 2.0))
        recessSk.name = 'Hull_Recess'
        ship_outline(recessSk, aft0 - recessGap, fwd0 + recessGap, PROM_INSET - recessGap)
        ri = extrudes.createInput(recessSk.profiles.item(0),
                                  adsk.fusion.FeatureOperations.CutFeatureOperation)
        ri.participantBodies = [hullBody]
        ri.setDistanceExtent(True, adsk.core.ValueInput.createByString(
            '{} mm'.format(symmetric_value(recessDepth))))
        extrudes.add(ri)

        # ---------------------------------------------------------- the lifeboats
        boatTop = boatZ + boatHt / 2.0
        require(boatTop < hullH - gunwaleFillet - 0.5,
                'Lifeboats top out at {:.2f} mm, into the gunwale fillet at {:.2f} mm.'
                .format(boatTop, hullH - gunwaleFillet))
        require(boatZ - boatHt / 2.0 > keelFillet + 1.0, 'Lifeboats sit too low on the hull.')
        require(boatPitch > boatLen + 1.0, 'Lifeboat pitch is tighter than the pod length.')
        textBand = (boatZ - boatHt / 2.0) - keelFillet

        def oval_on_xz(name, yOffset, xc, zc, lengthX, heightZ):
            planeName = name.replace('Boat_', 'Boat_P_').replace('Mick_', 'Mick_P_')
            plane = offset_plane(planeName, root.xZConstructionPlane, yOffset)
            sk = root.sketches.add(plane)
            sk.name = name
            to_local = local_mapper(sk, ('x', 'z'))
            a, b = lengthX / 2.0, heightZ / 2.0
            sp = sk.sketchPoints
            quad = [sp.add(to_local(xc + a, zc)), sp.add(to_local(xc, zc + b)),
                    sp.add(to_local(xc - a, zc)), sp.add(to_local(xc, zc - b))]
            through = [to_local(xc + a * DIAG, zc + b * DIAG),
                       to_local(xc - a * DIAG, zc + b * DIAG),
                       to_local(xc - a * DIAG, zc - b * DIAG),
                       to_local(xc + a * DIAG, zc - b * DIAG)]
            arcs = sk.sketchCurves.sketchArcs
            for i in range(4):
                arcs.addByThreePoints(quad[i], through[i], quad[(i + 1) % 4])
            require(sk.profiles.count == 1,
                    'Sketch "{}" produced {} profiles, expected 1.'
                    .format(sk.name, sk.profiles.count))
            return sk.profiles.item(0)

        def join_bump(nameBase, sign, xc, zc, innerLen, innerHt, outerLen, outerHt,
                      surfaceY, sink, standoff):
            """Loft a pod from just inside a surface to a smaller profile standing
            off it. Tapering the outer profile lets it blend into a curved surface
            instead of hovering at its edges."""
            inner = oval_on_xz('{}_in'.format(nameBase), sign * (surfaceY - sink),
                               xc, zc, innerLen, innerHt)
            outer = oval_on_xz('{}_out'.format(nameBase), sign * (surfaceY + standoff),
                               xc, zc, outerLen, outerHt)
            bl = lofts.createInput(adsk.fusion.FeatureOperations.JoinFeatureOperation)
            bl.loftSections.add(inner)
            bl.loftSections.add(outer)
            bl.isSolid = True
            lofts.add(bl)

        def boat_y(xc):
            """Where the pod's hull actually is -- the real arc, not the straight
            line. The straight-line model put the stern-most pod 1.86 mm too far
            in, which buried it inside the hull entirely."""
            return hull_surface_y(xc, boatZ)

        def boat_sag(xc):
            """How far the hull falls away under one pod, across the pod's own
            length. A fixed sink cannot cover this: near the bow the hull drops
            over a millimetre across 9 mm and the pod's forward end lifts off."""
            r = boatLen / 2.0
            here = boat_y(xc)
            if here is None:
                return 1.0e9
            worst = here
            for xx in (xc - r, xc + r):
                v = boat_y(xx)
                if v is None:
                    return 1.0e9
                worst = min(worst, v)
            return here - worst

        boatXs = []
        bx = boatFirstX
        while bx <= boatLastX:
            boatXs.append(bx)
            bx += boatPitch
        require(len(boatXs) > 0, 'No lifeboat stations -- check the pitch and range.')

        # Cull the stations the hull curves away from too fast, rather than
        # placing a pod that floats and having to delete it by hand afterwards.
        boatPlaced = [x for x in boatXs if boat_sag(x) <= boatMaxSag]
        boatSkipped = [x for x in boatXs if boat_sag(x) > boatMaxSag]
        require(len(boatPlaced) >= 3,
                'Only {} lifeboat stations survive the {:.1f} mm sag limit.'
                .format(len(boatPlaced), boatMaxSag))

        for bi, bxc in enumerate(boatPlaced):
            hullHalf = boat_y(bxc)
            require(hullHalf > boatHt,
                    'Hull is only {:.1f} mm half-wide at x={:.1f}.'.format(hullHalf, bxc))
            boatSink = boat_sag(bxc) + boatSinkMargin
            for side, sign in (('S', 1.0), ('P', -1.0)):
                join_bump('Boat_{}{}'.format(bi, side), sign, bxc, boatZ,
                          boatLen, boatHt, boatLen * 0.75, boatHt * 0.7,
                          hullHalf, boatSink, boatProud)

        # ------------------------------------------------------------ deck floors
        z0 = hullH
        promTopZ = z0 + PROM
        mainTopZ = promTopZ + 4 * FLOOR
        funnelTopZ = mainTopZ + 4.0
        bridgeTopZ = mainTopZ + 10.0
        bridgeAftX = 6.0

        floors = [
            ('Promenade',  z0,                  promTopZ,            PROM_INSET,  PROM_INSET,  aft(0),      fwd(0)),
            ('Main1',      promTopZ,            promTopZ + FLOOR,    MAIN_INSET,  MAIN_INSET,  aft(1),      fwd(1)),
            ('Main2',      promTopZ + FLOOR,    promTopZ + 2*FLOOR,  MAIN_INSET,  MAIN_INSET,  aft(2),      fwd(2)),
            ('Main3',      promTopZ + 2*FLOOR,  promTopZ + 3*FLOOR,  MAIN_INSET,  MAIN_INSET,  aft(3),      fwd(3)),
            ('Main4',      promTopZ + 3*FLOOR,  mainTopZ,            MAIN_INSET,  MAIN_INSET,  aft(4),      fwd(4)),
            ('FunnelDeck', mainTopZ,            funnelTopZ,          7.0,         8.0,         aft(5),      fwd(5)),
            ('Bridge',     mainTopZ,            bridgeTopZ,         10.0,        11.0,         bridgeAftX,  fwd(6)),
        ]

        def level_sketch(name, z, inset, xAft, xFwd):
            sk = root.sketches.add(plane_at(z))
            sk.name = name
            ship_outline(sk, xAft, xFwd, inset)
            return sk

        bodyBody = None
        aftMost = None
        for name, za, zb, i0, i1, a, f in floors:
            skLo = level_sketch('Deck_{}_lo'.format(name), za, i0, a, f)
            skHi = level_sketch('Deck_{}_hi'.format(name), zb, i1, a, f)
            op = (adsk.fusion.FeatureOperations.NewBodyFeatureOperation if bodyBody is None
                  else adsk.fusion.FeatureOperations.JoinFeatureOperation)
            li = lofts.createInput(op)
            li.loftSections.add(skLo.profiles.item(0))
            li.loftSections.add(skHi.profiles.item(0))
            li.isSolid = True
            loft = lofts.add(li)
            if bodyBody is None:
                bodyBody = loft.bodies.item(0)
                bodyBody.name = 'Body'
            if name == 'Main4':
                aftMost = a

        require(root.bRepBodies.itemByName('Body') is not None,
                'The deck floors did not join into a single Body.')

        # ------------------------------------------------- pockets (slots/grooves)
        def cut_pockets(sketchName, planeName, basePlane, offsetMM, depth, rects, target, axes):
            """rects in GLOBAL mm along axes[0]/axes[1]. Cut symmetrically about the
            pocket's mid-depth plane so the direction cannot come out backwards;
            the probed symmetric_value keeps the total depth right either way."""
            plane = offset_plane(planeName, basePlane, offsetMM)
            sk = root.sketches.add(plane)
            sk.name = sketchName
            to_local = local_mapper(sk, axes)
            sp = sk.sketchPoints
            lines = sk.sketchCurves.sketchLines
            for a0, a1, b0, b1 in rects:
                bl = sp.add(to_local(a0, b0))
                br = sp.add(to_local(a1, b0))
                tr = sp.add(to_local(a1, b1))
                tl = sp.add(to_local(a0, b1))
                lines.addByTwoPoints(bl, br)
                lines.addByTwoPoints(br, tr)
                lines.addByTwoPoints(tr, tl)
                lines.addByTwoPoints(tl, bl)
            require(sk.profiles.count == len(rects),
                    'Sketch "{}" produced {} profiles, expected {}.'
                    .format(sketchName, sk.profiles.count, len(rects)))
            ei = extrudes.createInput(all_profiles(sk),
                                      adsk.fusion.FeatureOperations.CutFeatureOperation)
            ei.participantBodies = [target]
            ei.setDistanceExtent(True, adsk.core.ValueInput.createByString(
                '{} mm'.format(symmetric_value(depth))))
            extrudes.add(ei)

        mainHalfBeam = B / 2.0 - MAIN_INSET
        promHalfBeam = B / 2.0 - PROM_INSET
        slotW = cube + 2 * clearance
        slotH = cube + 2 * clearance
        pitch = slotW + divider
        cubeFaceY = mainHalfBeam + cubeProud

        require(slotDepth > cube / 2.0,
                'Slot depth {:.1f} mm is under half the cube -- it would tip out.'.format(slotDepth))
        require(cubeFaceY > promHalfBeam + 0.5,
                'Cube face at {:.1f} mm against a {:.1f} mm promenade edge reads as flush.'
                .format(cubeFaceY, promHalfBeam))

        slotZ1 = mainTopZ - slotCeiling
        slotZ0 = slotZ1 - slotH
        require(abs(slotZ0 - promTopZ) < 1.5,
                'Slot floor at {:.1f} mm does not land on the promenade top at {:.1f} mm.'
                .format(slotZ0, promTopZ))

        arrayWidth = cubeN * slotW + (cubeN - 1) * divider
        arrayAft = -40.0
        arrayCenter = arrayAft + arrayWidth / 2.0
        require(arrayAft > sternTaperEnd + 1.0, 'Cube array starts inside the stern taper.')
        require(arrayAft + arrayWidth < bowTaperStart - 1.0, 'Cube array runs into the bow taper.')
        require(arrayAft > aftMost + 1.0, 'Cube array starts aft of the topmost main floor.')

        displayCenters = [arrayCenter + (i - (cubeN - 1) / 2.0) * pitch for i in range(cubeN)]
        cut_pockets('Cut_Slots_Display', 'Cut_P_Display', root.xZConstructionPlane,
                    -(mainHalfBeam - slotDepth / 2.0), slotDepth,
                    [(xc - slotW / 2.0, xc + slotW / 2.0, slotZ0, slotZ1) for xc in displayCenters],
                    bodyBody, ('x', 'z'))

        grooveRects = []
        zc = promTopZ + groovePitch
        while zc < mainTopZ - groovePitch / 2.0:
            grooveRects.append((sternTaperEnd + 1.0, bowTaperStart - 1.0,
                                zc - grooveHeight / 2.0, zc + grooveHeight / 2.0))
            zc += groovePitch
        require(len(grooveRects) > 0, 'groovePitch produced no deck lines.')
        cut_pockets('Cut_Grooves_Stbd', 'Cut_P_Groove_S', root.xZConstructionPlane,
                    mainHalfBeam - grooveDepth / 2.0, grooveDepth, grooveRects,
                    bodyBody, ('x', 'z'))
        cut_pockets('Cut_Grooves_Port', 'Cut_P_Groove_P', root.xZConstructionPlane,
                    -(mainHalfBeam - grooveDepth / 2.0), grooveDepth, grooveRects,
                    bodyBody, ('x', 'z'))

        # ------------------------------------------ spare cube pocket, hull stern
        sparePocketSize = cube + spareClearance
        spareZ0 = spareFloor
        spareZ1 = spareZ0 + sparePocketSize
        spareRoof = hullH - spareZ1
        transomHalf = sternTipW / 2.0
        require(spareRoof > 2.0, 'Not enough hull above the spare pocket.')
        require(sparePocketSize / 2.0 < transomHalf - 3.0,
                'Spare pocket leaves under 3 mm of transom wall.')
        cut_pockets('Cut_Spare', 'Cut_P_Spare', root.yZConstructionPlane,
                    sternX + spareDepth / 2.0, spareDepth,
                    [(-sparePocketSize / 2.0, sparePocketSize / 2.0, spareZ0, spareZ1)],
                    hullBody, ('y', 'z'))

        # Finger notches in the pocket's side walls. Clearance alone stops the cube
        # seizing, but with it sitting flush there is still nothing to grip, so the
        # side walls -- the only ones with material to spare -- get scalloped.
        transomHalfAtStern = half_width_at(sternX, 0.0)
        gripWall = transomHalfAtStern - sparePocketSize / 2.0 - spareGripDia / 2.0
        require(gripWall > 1.5,
                'Finger notches would leave only {:.2f} mm of transom wall.'
                .format(gripWall))
        gripSk = root.sketches.add(offset_plane(
            'Cut_P_SpareGrip', root.yZConstructionPlane, sternX + spareGripDepth / 2.0))
        gripSk.name = 'Cut_SpareGrip'
        gripLocal = local_mapper(gripSk, ('y', 'z'))
        for sgn in (-1.0, 1.0):
            gripSk.sketchCurves.sketchCircles.addByCenterRadius(
                gripLocal(sgn * sparePocketSize / 2.0,
                          spareZ0 + sparePocketSize / 2.0),
                mm(spareGripDia / 2.0))
        require(gripSk.profiles.count == 2,
                'Finger notch sketch produced {} profiles, expected 2.'
                .format(gripSk.profiles.count))
        gripIn = extrudes.createInput(all_profiles(gripSk),
                                      adsk.fusion.FeatureOperations.CutFeatureOperation)
        gripIn.participantBodies = [hullBody]
        gripIn.setDistanceExtent(True, adsk.core.ValueInput.createByString(
            '{} mm'.format(symmetric_value(spareGripDepth))))
        extrudes.add(gripIn)

        # -------------------------------------------------- hull sentiment text
        # CURVED lettering. Each glyph is placed on its own tangent frame along
        # the hull's real plan curve, so the run is not confined to the flat
        # midship zone -- about 99 mm of arc against 64 mm of flat. That extra
        # width is what lets the type be big enough for clean two-wall strokes.
        #
        # Raised and joined into the hull as one body. A flush inlay was
        # invisible in Fusion and exported as a loose body per glyph that the
        # slicer scattered across the plate.
        hullTextCentreX = (sternTaperEnd + bowTaperStart) / 2.0
        hullTextCentreZ = (hullTextBandLo + hullTextBandHi) / 2.0
        hullTextMaxH = hullTextBandHi - hullTextBandLo
        hullTextThick = hullTextBite + hullTextProud

        for sideTag in hullTextSides:
            require(sideTag in HULL_TEXT and HULL_TEXT[sideTag].strip(),
                    'HULL_TEXT has nothing for side {}.'.format(sideTag))
        require(hullTextBandLo > keelFillet + 1.0,
                'Sentiment band starts at {:.1f} mm, inside the {:.1f} mm keel fillet.'
                .format(hullTextBandLo, keelFillet))
        require(hullTextBandHi < boatZ - boatHt / 2.0 - 1.0,
                'Sentiment band tops out at {:.1f} mm, into the lifeboats at {:.1f} mm.'
                .format(hullTextBandHi, boatZ - boatHt / 2.0))
        require(hullTextProud < boatProud,
                'Lettering stands {:.1f} mm proud, further than the {:.1f} mm lifeboats.'
                .format(hullTextProud, boatProud))
        require(hullTextBite > hullTextMaxTwist,
                'A {:.1f} mm bite cannot swallow {:.1f} mm of surface twist.'
                .format(hullTextBite, hullTextMaxTwist))

        def surface_slope(x):
            h = 0.05
            a = hull_surface_y(x - h, hullTextCentreZ)
            b = hull_surface_y(x + h, hullTextCentreZ)
            if a is None or b is None:
                return None
            return (b - a) / (2.0 * h)

        def surface_twist(x):
            """How far the hull shifts across the text band at this station. A
            flat glyph spanning the band buries at one end and floats at the
            other once this exceeds the bite -- it is what stops the lettering
            reaching further forward, since the bow rakes and the stern does not."""
            lo = hull_surface_y(x, hullTextBandLo)
            hi = hull_surface_y(x, hullTextBandHi)
            if lo is None or hi is None:
                return 1.0e9
            return abs(lo - hi)

        def run_usable(x):
            sl = surface_slope(x)
            return (sl is not None
                    and surface_twist(x) <= hullTextMaxTwist
                    and abs(math.degrees(math.atan(sl))) <= hullTextMaxTangent)

        # Reach out symmetrically, so the block stays centred where it is now.
        hullTextReach = 0.0
        while hullTextReach < L / 2.0:
            nxt = hullTextReach + 0.1
            if not (run_usable(hullTextCentreX - nxt)
                    and run_usable(hullTextCentreX + nxt)):
                break
            hullTextReach = nxt
        require(hullTextReach > 20.0,
                'Hull gives only {:.1f} mm each way before it twists or turns too '
                'far for flat glyphs.'.format(hullTextReach))

        # Arc-length table. Glyphs are spaced along the surface, not along its x
        # projection, or the text bunches up wherever the hull curves.
        stationTable = [(0.0, hullTextCentreX)]
        for direction in (-1.0, 1.0):
            s, x = 0.0, hullTextCentreX
            for _ in range(int(hullTextReach / 0.05) + 2):
                left = hullTextReach - abs(x - hullTextCentreX)
                if left <= 1.0e-9:
                    break
                nx = x + direction * min(0.05, left)
                y0 = hull_surface_y(x, hullTextCentreZ)
                y1 = hull_surface_y(nx, hullTextCentreZ)
                require(y0 is not None and y1 is not None,
                        'Lost the hull surface while walking the sentiment run.')
                s += direction * math.hypot(nx - x, y1 - y0)
                stationTable.append((s, nx))
                x = nx
        stationTable.sort()
        hullTextArc = stationTable[-1][0] - stationTable[0][0]
        hullTextRun = hullTextArc - 2.0 * hullTextMargin
        require(hullTextRun > 20.0,
                'Only {:.1f} mm of run left after margins.'.format(hullTextRun))

        def hull_station(s):
            """x at arc length s from the text centre, measured along the side."""
            require(stationTable[0][0] - 1.0e-6 <= s <= stationTable[-1][0] + 1.0e-6,
                    'A glyph at {:.2f} mm runs off the usable hull run.'.format(s))
            lo, hi = 0, len(stationTable) - 1
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if stationTable[mid][0] <= s:
                    lo = mid
                else:
                    hi = mid
            s0, x0 = stationTable[lo]
            s1, x1 = stationTable[hi]
            if abs(s1 - s0) < 1.0e-9:
                return x0
            return x0 + (x1 - x0) * (s - s0) / (s1 - s0)

        # Fit pass: measure each side once at the seed size, then give both sides
        # one shared scale so they come out the same size whatever their lengths.
        seedSize = {}
        for sideTag in hullTextSides:
            f, sk = text_tool('Hull_TextFit_{}'.format(sideTag),
                              HULL_TEXT[sideTag], hullTextSeedEm, 1.0)
            lo, hi = bodies_extent([f])
            seedSize[sideTag] = (hi[0] - lo[0], hi[1] - lo[1])
            drop(f, 'sentiment fit extrude for side ' + sideTag)
            drop(sk, 'sentiment fit sketch for side ' + sideTag)

        # Each side's own best fit, then optionally pull both down to the
        # smaller so they match. The longer string sets the shared size.
        sideScale = {}
        for sideTag, (w, h) in seedSize.items():
            require(w > 0.1 and h > 0.1,
                    'Sentiment fit measured nothing for side {}.'.format(sideTag))
            sideScale[sideTag] = min(hullTextRun / w, hullTextMaxH / h)
        if hullTextSharedScale:
            common = min(sideScale.values())
            sideScale = dict((k, common) for k in sideScale)
        hullTextEm = dict((k, hullTextSeedEm * v) for k, v in sideScale.items())
        for sideTag, em in hullTextEm.items():
            require(em > 1.0,
                    'Sentiment fit produced a degenerate size on side {}.'.format(sideTag))
        hullInk = dict((k, (seedSize[k][0] * sideScale[k], seedSize[k][1] * sideScale[k]))
                       for k in sideScale)

        hullStrokes, hullGlyphCounts, hullFitRatios = [], [], []
        for sideTag in ('S', 'P'):
            if sideTag not in hullTextSides:
                continue
            sideSign = 1.0 if sideTag == 'S' else -1.0

            feat, _ = text_tool('Hull_Text_{}'.format(sideTag),
                                HULL_TEXT[sideTag], hullTextEm[sideTag], hullTextThick)
            require(feat.bodies.count >= hullTextMinGlyphs,
                    'The sentiment on side {} came out as {} solid(s). A script that '
                    'joins into one piece cannot be curved glyph by glyph.'
                    .format(sideTag, feat.bodies.count))
            hullGlyphCounts.append(feat.bodies.count)

            # Stroke width, measured before the join consumes the glyphs. For a
            # thin prism of thickness t, volume/t is the ink area and
            # (surface - 2*ink)/t is the outline, about twice the stroke run.
            glyphBodies = tool_bodies([feat])
            volMM = sum(b.physicalProperties.volume for b in glyphBodies) * 1000.0
            areaMM = sum(b.physicalProperties.area for b in glyphBodies) * 100.0
            inkArea = volMM / hullTextThick
            outline = (areaMM - 2.0 * inkArea) / hullTextThick
            require(inkArea > 1.0 and outline > 1.0,
                    'Sentiment on side {} measured as nonsense.'.format(sideTag))
            strokeW = 2.0 * inkArea / outline
            require(strokeW > hullTextMinStroke,
                    'Sentiment strokes average about {:.2f} mm, under the {:.2f} mm a '
                    '0.4 mm nozzle can lay down at all.'
                    .format(strokeW, hullTextMinStroke))
            hullStrokes.append(strokeW)

            # Centre the block on the origin, then read each glyph's offset from
            # that centre. Fusion has already kerned the line; this preserves it
            # exactly, and a space simply shows up as a gap between glyphs.
            lo, hi = bodies_extent([feat])
            translate([feat], -(lo[0] + hi[0]) / 2.0, -(lo[1] + hi[1]) / 2.0)
            layout = []
            for i in range(feat.bodies.count):
                bb = feat.bodies.item(i).boundingBox
                layout.append((((bb.minPoint.x + bb.maxPoint.x) / 2.0) * 10.0,
                               ((bb.minPoint.y + bb.maxPoint.y) / 2.0) * 10.0))

            for i, (gx, gy) in enumerate(layout):
                # Stations run along the READING direction, not along +x. On
                # starboard r points aft, so laying glyphs out by +x put them in
                # reverse order -- individually correct, but the line read as a
                # mirror image. Port happened to agree with +x, which is why only
                # one side showed it.
                x = hull_station(-sideSign * gx)
                y = hull_surface_y(x, hullTextCentreZ)
                slope = surface_slope(x)
                require(y is not None and slope is not None,
                        'No hull surface at station x={:.1f}.'.format(x))
                nlen = math.hypot(slope, 1.0)
                nvec = (-slope / nlen, sideSign / nlen, 0.0)   # outward normal
                uvec = (0.0, 0.0, 1.0)
                rvec = (-nvec[1], nvec[0], 0.0)                # up x n, right-handed
                # Local (gx, gy, bite) has to land on the surface at this glyph's
                # own height. Subtracting gy here instead flattened every glyph
                # onto the band centre and threw the baseline away.
                origin = (x - hullTextBite * nvec[0] - gx * rvec[0],
                          sideSign * y - hullTextBite * nvec[1] - gx * rvec[1],
                          hullTextCentreZ)
                matrix = adsk.core.Matrix3D.create()
                require(matrix.setWithCoordinateSystem(
                            adsk.core.Point3D.create(mm(origin[0]), mm(origin[1]),
                                                     mm(origin[2])),
                            adsk.core.Vector3D.create(rvec[0], rvec[1], rvec[2]),
                            adsk.core.Vector3D.create(uvec[0], uvec[1], uvec[2]),
                            adsk.core.Vector3D.create(nvec[0], nvec[1], nvec[2])),
                        'Could not build the frame for glyph {} on side {}.'
                        .format(i, sideTag))
                move_solids([feat.bodies.item(i)], matrix)

            hullBody = root.bRepBodies.itemByName('Hull')
            require(hullBody is not None, 'Hull went missing before the sentiment join.')
            volBefore = hullBody.physicalProperties.volume
            hci = combines.createInput(hullBody, collect([feat]))
            hci.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
            hci.isKeepToolBodies = False
            combines.add(hci)
            hullBody = root.bRepBodies.itemByName('Hull')
            require(hullBody is not None, 'Hull vanished during the sentiment join.')

            # Only the proud part is new material; the bite was already hull. The
            # ratio is reported rather than pinned, because it also carries how
            # well the surface model matched the loft Fusion actually built.
            added = (hullBody.physicalProperties.volume - volBefore) * 1000.0
            expect = inkArea * hullTextProud
            ratio = added / expect if expect > 1.0e-9 else 0.0
            hullFitRatios.append(ratio)
            require(0.25 < ratio < 2.2,
                    'Sentiment on side {} added {:.0f} mm3 against {:.0f} expected '
                    '(x{:.2f}) -- the glyphs are not sitting on the hull.'
                    .format(sideTag, added, expect, ratio))

        hullStrokeMin = min(hullStrokes) if hullStrokes else 0.0

        # ------------------------------------------------------------- the cubes
        cubeBodies = []
        cubeCentres = {}

        def make_cube(name, x0, y0, zBase):
            sk = root.sketches.add(plane_at(zBase))
            sk.name = 'Cube_Sk_{}'.format(name)
            sp = sk.sketchPoints
            bl = sp.add(P(x0, y0))
            br = sp.add(P(x0 + cube, y0))
            tr = sp.add(P(x0 + cube, y0 + cube))
            tl = sp.add(P(x0, y0 + cube))
            lines = sk.sketchCurves.sketchLines
            lines.addByTwoPoints(bl, br)
            lines.addByTwoPoints(br, tr)
            lines.addByTwoPoints(tr, tl)
            lines.addByTwoPoints(tl, bl)
            require(sk.profiles.count == 1, 'Cube sketch "{}" did not close.'.format(sk.name))
            ei = extrudes.createInput(
                sk.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
            ei.setDistanceExtent(False, adsk.core.ValueInput.createByString('cubeSize'))
            body = extrudes.add(ei).bodies.item(0)
            body.name = 'Cube_{}'.format(name)
            cubeBodies.append(body)
            cubeCentres[body.name] = (x0 + cube / 2.0, y0 + cube / 2.0, zBase + cube / 2.0)
            return body

        for i, xc in enumerate(displayCenters):
            make_cube(str(i + 1), xc - cube / 2.0, -cubeFaceY, slotZ0 + clearance)
        make_cube('4_Spare', sternX + spareDepth - cube, -cube / 2.0,
                  spareZ0 + spareClearance / 2.0)

        for body in cubeBodies:
            fillet_edges(list(body.edges), 'cubeEdgeFillet', 'cube edge')

        # ------------------------------------------------- digits on every face
        # Every one of the 24 faces carries a digit, and that is forced rather
        # than chosen: 000/111/222/333 are all under 365, so 0-3 each need three
        # cubes; 344/355/266/277/288/299 are too, so 4-9 each need two. That is
        # 4*3 + 6*2 = 24 faces against 24 available. No face can be left blank.
        CUBE_DIGITS = [
            ('Cube_1',       'A', ['1', '2', '3', '4', '5', '6']),
            ('Cube_2',       'B', ['0', '2', '3', '4', '7', '8']),
            ('Cube_3',       'C', ['0', '1', '3', '5', '7', '9']),
            ('Cube_4_Spare', 'D', ['0', '1', '2', '6', '8', '9']),
        ]

        # digits[i] lands on FACE_ORDER[i]. The in-plane right vector is derived
        # as up x normal, which is always right-handed, so no face can come out
        # mirrored -- that failure mode is designed out rather than tested for.
        FACE_ORDER = ['-Y', '+Y', '+X', '-X', '+Z', '-Z']
        FACE_FRAME = {
            '+X': ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            '-X': ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            '+Y': ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            '-Y': ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
            '+Z': ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
            '-Z': ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
        }

        def validate_digit_sets():
            """Prove the digit sets can still render every value 0-365."""
            sets = {}
            for bodyName, label, digits in CUBE_DIGITS:
                require(len(digits) == 6,
                        'Cube {} has {} faces, needs 6.'.format(label, len(digits)))
                require(len(set(digits)) == 6, 'Cube {} repeats a digit.'.format(label))
                sets[label] = set(digits)
            require(len(sets) == 4, 'Expected four distinctly labelled cubes.')
            labels = list(sets.keys())
            worstN, worstCount = None, None
            for n in range(0, 366):
                want = list('{:03d}'.format(n))
                count = 0
                for combo in permutations(labels, 3):
                    if all(want[i] in sets[combo[i]] for i in range(3)):
                        count += 1
                require(count > 0, 'These digit sets cannot display {:d}.'.format(n))
                if worstCount is None or count < worstCount:
                    worstN, worstCount = n, count
            return worstN, worstCount

        worstN, worstCount = validate_digit_sets()

        markHead = mickHead * markScale
        markEar = mickEar * markScale
        markOffset = earOffset * markScale
        markTop = markCentreY + markOffset * EAR_COS + markEar / 2.0
        markBot = markCentreY - markHead / 2.0
        faceSafe = cube / 2.0 - cubeEdgeFillet
        require(markBot > -faceSafe,
                'Cube Mickey reaches {:.2f} mm, past the {:.2f} mm safe face area.'
                .format(markBot, faceSafe))

        cubeToolHeight = digitRecess + toolOvershoot

        # Calibration. Ask the font how tall it actually draws instead of
        # assuming some fraction of the em size -- a script face like Waltograph
        # has nothing like text-face metrics.
        calFeat, calSk = text_tool('Cube_Digit_Calibration', '0123456789',
                                   digitEmSeed, cubeToolHeight)
        calLo, calHi = bodies_extent([calFeat])
        calH = calHi[1] - calLo[1]
        calW = calHi[0] - calLo[0]
        require(calH > 0.1, 'Calibration text measured no height.')
        require(calW > 4.0 * calH,
                'Calibration text wrapped onto more than one line, so its height '
                'is meaningless. Widen the box in text_tool.')
        digitEmHeight = digitEmSeed * digitInkHeight / calH
        require(0.2 * digitEmSeed < digitEmHeight < 5.0 * digitEmSeed,
                'Calibration wants a {:.1f} mm em to draw {:.1f} mm of ink, which '
                'is not credible -- check the font actually has numerals.'
                .format(digitEmHeight, digitInkHeight))
        drop(calFeat, 'the digit calibration extrude')
        drop(calSk, 'the digit calibration sketch')

        def mark_tool(sketchName):
            """The funnel emblem, scaled down, used as the 6/9 orientation mark."""
            sk = root.sketches.add(root.xYConstructionPlane)
            sk.name = sketchName
            circles = sk.sketchCurves.sketchCircles
            circles.addByCenterRadius(P(0.0, markCentreY), mm(markHead / 2.0))
            for sgn in (-1.0, 1.0):
                circles.addByCenterRadius(
                    P(sgn * markOffset * EAR_SIN, markCentreY + markOffset * EAR_COS),
                    mm(markEar / 2.0))
            require(sk.profiles.count > 0, 'Cube Mickey produced no profiles.')
            ei = extrudes.createInput(all_profiles(sk),
                                      adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
            ei.setDistanceExtent(False, adsk.core.ValueInput.createByString(
                '{} mm'.format(cubeToolHeight)))
            return label_tool_bodies(extrudes.add(ei))

        inkSizes = []

        def engrave_face(bodyName, centre, faceKey, digit, withMark):
            anchorY = digitShiftMark if withMark else 0.0
            toolFeats = [text_tool('Cube_Digit_{}_{}'.format(bodyName, faceKey),
                                   digit, digitEmHeight, cubeToolHeight)[0]]

            # Centre on the ink, not on the text box.
            lo, hi = bodies_extent(toolFeats)
            inkW, inkH = hi[0] - lo[0], hi[1] - lo[1]
            translate(toolFeats,
                      -(lo[0] + hi[0]) / 2.0,
                      anchorY - (lo[1] + hi[1]) / 2.0)
            inkSizes.append((inkW, inkH))

            top = anchorY + inkH / 2.0
            bot = anchorY - inkH / 2.0
            require(inkW / 2.0 < faceSafe and top < faceSafe and bot > -faceSafe,
                    'Digit "{}" measures {:.1f} x {:.1f} mm and spans y {:.1f} to '
                    '{:.1f}, outside the {:.1f} mm safe face area. Lower '
                    'digitInkHeight.'.format(digit, inkW, inkH, bot, top, faceSafe))
            if withMark:
                require(bot - markTop > digitMarkGap,
                        'Digit "{}" bottoms out at {:.2f} mm, only {:.2f} mm clear '
                        'of the Mickey at {:.2f} mm. Raise digitShiftMark or lower '
                        'markCentreY.'.format(digit, bot, bot - markTop, markTop))
                toolFeats.append(mark_tool(
                    'Cube_Mick_{}_{}'.format(bodyName, faceKey)))

            n, u = FACE_FRAME[faceKey]
            r = (u[1] * n[2] - u[2] * n[1],
                 u[2] * n[0] - u[0] * n[2],
                 u[0] * n[1] - u[1] * n[0])
            inset = cube / 2.0 - digitRecess
            matrix = adsk.core.Matrix3D.create()
            require(matrix.setWithCoordinateSystem(
                        adsk.core.Point3D.create(mm(centre[0] + n[0] * inset),
                                                 mm(centre[1] + n[1] * inset),
                                                 mm(centre[2] + n[2] * inset)),
                        adsk.core.Vector3D.create(r[0], r[1], r[2]),
                        adsk.core.Vector3D.create(u[0], u[1], u[2]),
                        adsk.core.Vector3D.create(n[0], n[1], n[2])),
                    'Could not build the placement frame for face ' + faceKey)
            move_by_matrix(toolFeats, matrix)

            target = root.bRepBodies.itemByName(bodyName)
            require(target is not None, 'Cube body "{}" is missing.'.format(bodyName))
            volBefore = target.physicalProperties.volume

            ci = combines.createInput(target, collect(toolFeats))
            ci.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
            ci.isKeepToolBodies = False
            combines.add(ci)

            target = root.bRepBodies.itemByName(bodyName)
            require(target is not None,
                    'Cube "{}" vanished while engraving {}.'.format(bodyName, digit))
            removed = volBefore - target.physicalProperties.volume
            # ~0.3% expected per face. Zero means the tool landed off the cube;
            # a large bite means the placement frame is wrong.
            require(removed > 1.0e-5,
                    'Engraving "{}" on face {} of {} removed nothing -- the tool '
                    'landed off the cube.'.format(digit, faceKey, bodyName))
            require(removed < 0.08 * volBefore,
                    'Engraving "{}" on face {} of {} removed {:.1f}% of the cube -- '
                    'the tool is mis-oriented.'
                    .format(digit, faceKey, bodyName, 100.0 * removed / volBefore))

        marked = []
        for bodyName, label, digits in CUBE_DIGITS:
            require(bodyName in cubeCentres,
                    'No cube named "{}" was built.'.format(bodyName))
            for faceKey, digit in zip(FACE_ORDER, digits):
                withMark = MARK_6_AND_9 and digit in ('6', '9')
                if withMark:
                    marked.append('{}:{}'.format(label, digit))
                engrave_face(bodyName, cubeCentres[bodyName], faceKey, digit, withMark)

        inkHiMin = min(h for w, h in inkSizes)
        inkHiMax = max(h for w, h in inkSizes)
        inkWidest = max(w for w, h in inkSizes)

        # ----------------------------------------------------------- the funnels
        stackXs = [stackCentreX - stackSpacing / 2.0, stackCentreX + stackSpacing / 2.0]
        stackTotalH = stackBodyH + stackCapH
        stackTopZ = funnelTopZ + stackTotalH
        neckRake = stackRake * stackBodyH / stackTotalH
        rakeAngle = math.degrees(math.atan2(stackRake, stackTotalH))
        deckHalfBeam = B / 2.0 - 8.0

        require(rakeAngle < 40.0, 'Funnel rake is past the self-support limit.')
        for xc in stackXs:
            require(xc + stackBaseL / 2.0 < bridgeAftX - 1.0,
                    'Funnel at x={:.1f} runs into the bridge block.'.format(xc))
            require(xc - stackRake - stackCapL / 2.0 > aft(5) + 1.0,
                    'Funnel at x={:.1f} leans past the aft end of the funnel deck.'.format(xc))
        require(stackSpacing > stackBaseL + 2.0, 'Funnels would overlap.')
        require(stackBaseW / 2.0 < deckHalfBeam - 1.0, 'Funnel is wider than the funnel deck.')
        require(stackCapL > stackTopL and stackCapW > stackTopW, 'Cap must exceed the funnel top.')

        # Two pins, deliberately different diameters. Two identical pins would let
        # the funnel seat 180 degrees round, which with the rake would lean it
        # forward instead of aft. Aft pin is the fat one.
        pins = [(-pegSpacing / 2.0, pegDiaAft), (pegSpacing / 2.0, pegDiaFwd)]
        require(pegDiaAft != pegDiaFwd,
                'Pins must differ in diameter, or the funnel can seat backwards.')
        for dxPin, dPin in pins:
            frac = dxPin / (stackBaseL / 2.0)
            hw = (stackBaseW / 2.0) * math.sqrt(max(1.0 - frac * frac, 0.0))
            reliefR = (dPin + clearance + socketRelief) / 2.0
            require(hw > reliefR + 1.0,
                    'Pin at dx={:.1f} leaves only {:.1f} mm of funnel wall once the '
                    'socket relief is cut.'.format(dxPin, hw - reliefR))

        def oval_profile(sketchName, z, xc, lengthX, widthY):
            sk = root.sketches.add(plane_at(z))
            sk.name = sketchName
            a, b = lengthX / 2.0, widthY / 2.0
            sp = sk.sketchPoints
            quad = [sp.add(P(xc + a, 0.0)), sp.add(P(xc, b)),
                    sp.add(P(xc - a, 0.0)), sp.add(P(xc, -b))]
            through = [P(xc + a * DIAG, b * DIAG), P(xc - a * DIAG, b * DIAG),
                       P(xc - a * DIAG, -b * DIAG), P(xc + a * DIAG, -b * DIAG)]
            arcs = sk.sketchCurves.sketchArcs
            for i in range(4):
                arcs.addByThreePoints(quad[i], through[i], quad[(i + 1) % 4])
            require(sk.profiles.count == 1,
                    'Sketch "{}" did not close into one oval.'.format(sketchName))
            return sk.profiles.item(0)

        def funnel_centre_x(xcBase, z):
            return xcBase - stackRake * (z - funnelTopZ) / stackTotalH

        def funnel_surface_y(z, dx):
            """Half-width of the funnel's oval at height z, dx fore-aft of its own
            centreline -- this is what seats each emblem circle on the curve."""
            f = (z - funnelTopZ) / stackBodyH
            a = (stackBaseL + (stackTopL - stackBaseL) * f) / 2.0
            b = (stackBaseW + (stackTopW - stackBaseW) * f) / 2.0
            ratio = dx / a
            require(abs(ratio) < 0.92, 'Emblem circle runs off the funnel.')
            return b * math.sqrt(1.0 - ratio * ratio)

        mickCircles = [
            (0.0, 0.0, mickHead),
            (-earOffset * EAR_SIN, earOffset * EAR_COS, mickEar),
            (earOffset * EAR_SIN, earOffset * EAR_COS, mickEar),
        ]

        def emblem_sink(zc, dx, dia):
            """How deep this circle's back face has to start.

            The funnel is an oval in plan, so a flat disc laid on it lifts off at
            the rim unless the back face begins below the shallowest point the
            disc covers. Measured off the real oval, not assumed."""
            r = dia / 2.0
            here = funnel_surface_y(zc, dx)
            worst = here
            for ddx in (dx - r, dx, dx + r):
                for ddz in (zc - r, zc, zc + r):
                    worst = min(worst, funnel_surface_y(ddz, ddx))
            return here - worst + mickSinkMargin

        mickZ = funnelTopZ + stackBodyH * mickFrac
        mickTop = mickZ + max(dz + d / 2.0 for dx, dz, d in mickCircles)
        mickBot = mickZ + min(dz - d / 2.0 for dx, dz, d in mickCircles)
        require(mickBot > funnelTopZ + 1.0 and mickTop < funnelTopZ + stackBodyH - 1.0,
                'Mickey spans z {:.1f}-{:.1f}, outside the red band.'.format(mickBot, mickTop))

        for i, xc in enumerate(stackXs):
            tag = i + 1
            neckX = xc - neckRake
            capX = xc - stackRake

            bodyLo = oval_profile('Stack_{}_base'.format(tag), funnelTopZ, xc,
                                  stackBaseL, stackBaseW)
            bodyHi = oval_profile('Stack_{}_neck'.format(tag), funnelTopZ + stackBodyH, neckX,
                                  stackTopL, stackTopW)
            li = lofts.createInput(adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
            li.loftSections.add(bodyLo)
            li.loftSections.add(bodyHi)
            li.isSolid = True
            stackBody = lofts.add(li).bodies.item(0)
            stackBody.name = 'Stack_{}'.format(tag)

            capLo = oval_profile('Stack_{}_capLo'.format(tag), funnelTopZ + stackBodyH, neckX,
                                 stackCapL, stackCapW)
            capHi = oval_profile('Stack_{}_capHi'.format(tag), stackTopZ, capX,
                                 stackCapL, stackCapW)
            ci = lofts.createInput(adsk.fusion.FeatureOperations.JoinFeatureOperation)
            ci.loftSections.add(capLo)
            ci.loftSections.add(capHi)
            ci.isSolid = True
            lofts.add(ci)

            # Pins up from the deck, sockets down into the funnel -- this way round
            # so the funnel never has to print balanced on a stub.
            pegSk = root.sketches.add(plane_at(funnelTopZ))
            pegSk.name = 'Stack_{}_pegs'.format(tag)
            for dxPin, dPin in pins:
                pegSk.sketchCurves.sketchCircles.addByCenterRadius(
                    P(xc + dxPin, 0.0), mm(dPin / 2.0))
            require(pegSk.profiles.count == 2,
                    'Pin sketch for stack {} produced {} profiles, expected 2.'
                    .format(tag, pegSk.profiles.count))
            pegIn = extrudes.createInput(all_profiles(pegSk),
                                         adsk.fusion.FeatureOperations.JoinFeatureOperation)
            pegIn.participantBodies = [bodyBody]
            pegIn.setDistanceExtent(False, adsk.core.ValueInput.createByString(
                '{} mm'.format(pegH)))
            extrudes.add(pegIn)

            sockSk = root.sketches.add(plane_at(funnelTopZ))
            sockSk.name = 'Stack_{}_sockets'.format(tag)
            for dxPin, dPin in pins:
                sockSk.sketchCurves.sketchCircles.addByCenterRadius(
                    P(xc + dxPin, 0.0), mm((dPin + clearance) / 2.0))
            require(sockSk.profiles.count == 2,
                    'Socket sketch for stack {} produced {} profiles, expected 2.'
                    .format(tag, sockSk.profiles.count))
            sockIn = extrudes.createInput(all_profiles(sockSk),
                                          adsk.fusion.FeatureOperations.CutFeatureOperation)
            sockIn.participantBodies = [stackBody]
            sockIn.setDistanceExtent(False, adsk.core.ValueInput.createByString(
                '{} mm'.format(pegH + socketExtra)))
            extrudes.add(sockIn)

            # Counterbore at the socket mouth. The funnel prints base down, so
            # elephant's foot pinches the mouth shut, and the pin flares where it
            # meets the deck -- between them the funnel stood proud of the deck.
            reliefSk = root.sketches.add(plane_at(funnelTopZ))
            reliefSk.name = 'Stack_{}_relief'.format(tag)
            for dxPin, dPin in pins:
                reliefSk.sketchCurves.sketchCircles.addByCenterRadius(
                    P(xc + dxPin, 0.0), mm((dPin + clearance + socketRelief) / 2.0))
            require(reliefSk.profiles.count == 2,
                    'Socket relief sketch for stack {} produced {} profiles, expected 2.'
                    .format(tag, reliefSk.profiles.count))
            reliefIn = extrudes.createInput(
                all_profiles(reliefSk), adsk.fusion.FeatureOperations.CutFeatureOperation)
            reliefIn.participantBodies = [stackBody]
            reliefIn.setDistanceExtent(False, adsk.core.ValueInput.createByString(
                '{} mm'.format(socketReliefDepth)))
            extrudes.add(reliefIn)

            # No taper on the emblem. join_bump's 0.9x outer profile exists so a
            # lifeboat pod blends into the curved hull, but on overlapping circles
            # it shrinks the visible face until the ears only graze the head --
            # 0.50 mm of overlap became 0.03 mm, which is what made Mickey look
            # like three loose blobs. Straight prisms, so the silhouette merges.
            for side, sign in (('S', 1.0), ('P', -1.0)):
                for ci2, (dx, dz, dia) in enumerate(mickCircles):
                    czc = mickZ + dz
                    cxc = funnel_centre_x(xc, czc) + dx
                    surfY = funnel_surface_y(czc, dx)
                    join_bump('Mick_{}{}_{}'.format(tag, side, ci2), sign, cxc, czc,
                              dia, dia, dia, dia, surfY,
                              emblem_sink(czc, dx, dia), mickProud)

        # -------------------------------------------------------- body manifest
        # Anything beyond these eight is scratch geometry that survived, and it
        # would export as a stray part. Name it rather than ship it.
        EXPECTED_BODIES = ['Hull', 'Body', 'Cube_1', 'Cube_2', 'Cube_3',
                           'Cube_4_Spare', 'Stack_1', 'Stack_2']
        actualBodies = sorted(b.name for b in root.bRepBodies)
        strays = [nm for nm in actualBodies if nm not in EXPECTED_BODIES]
        missing = [nm for nm in EXPECTED_BODIES if nm not in actualBodies]
        require(not missing,
                'These parts were never built: {}.'.format(', '.join(missing)))
        require(not strays,
                '{} stray bodies survived and would export as extra parts: {}{}'
                .format(len(strays), ', '.join(strays[:15]),
                        ' ...' if len(strays) > 15 else ''))

        # ------------------------------------------------------------------ tidy
        for s in root.sketches:
            try:
                s.isVisible = False
            except:
                pass

        ui.messageBox('Built.\n\n'
                      'Symmetric extrude probed as {}.\n'
                      'Funnels keyed by two pins: {:.0f} mm aft, {:.0f} mm forward, '
                      '{:.0f} mm apart.\n'
                      'Sockets {:.1f} mm deep for {:.0f} mm pins, with a {:.1f} mm mouth relief.\n'
                      'Slots {:.0f} mm deep, cubes {:.0f} mm proud. Text band {:.1f} mm.\n'
                      'Transom pocket {:.1f} mm slack, notched {:.0f} mm each side.\n'
                      'Lifeboats: {} placed a side, {} dropped for hull sag over {:.1f} mm{}.\n\n'
                      'Font resolved to "{}"{}.\n'
                      'Digits: 24 faces in "{}", recessed {:.2f} mm ({:.0f} layers at 0.2).\n'
                      'Calibrated to a {:.1f} mm em; measured ink {:.1f}-{:.1f} mm tall, '
                      'widest {:.1f} mm, centred on the ink.\n'
                      'Mickey mark on {}.\n'
                      'Hardest countdown value is {:03d}, with {} valid arrangements.\n\n'
                      'Sentiment, curved along the hull over {:.1f} mm of arc, '
                      '{} scale:\n{}\n'
                      'Raised {:.2f} mm, {} glyphs a side. Measured stroke about '
                      '{:.2f} mm{}.\nJoin volume came out x{:.2f} of expected.\n\n'
                      'Bodies in the model: {} -- {}.'
                      .format('PER SIDE' if SYMMETRIC_PER_SIDE else 'TOTAL',
                              pegDiaAft, pegDiaFwd, pegSpacing,
                              pegH + socketExtra, pegH, socketRelief,
                              slotDepth, cubeProud, textBand,
                              spareClearance, spareGripDia,
                              len(boatPlaced), len(boatSkipped), boatMaxSag,
                              '' if not boatSkipped else
                              ' (at x ' + ', '.join('{:.0f}'.format(v)
                                                    for v in boatSkipped) + ')',
                              fontInUse,
                              '' if fontInUse == FONT_NAME
                              else ' (NOT your first choice, "{}")'.format(FONT_NAME),
                              fontInUse, digitRecess, digitRecess / 0.2,
                              digitEmHeight, inkHiMin, inkHiMax, inkWidest,
                              ', '.join(marked) if marked else 'off',
                              worstN, worstCount,
                              hullTextArc,
                              'shared' if hullTextSharedScale else 'per-side',
                              '\n'.join('  {}: "{}"  {:.1f} x {:.1f} mm at a {:.1f} mm em'
                                        .format(s, HULL_TEXT[s], hullInk[s][0],
                                                hullInk[s][1], hullTextEm[s])
                                        for s in hullTextSides),
                              hullTextProud,
                              '/'.join(str(n) for n in hullGlyphCounts),
                              hullStrokeMin,
                              '' if hullStrokeMin >= hullTextWarnStroke else
                              ' -- thin for a colour change, look at it before printing',
                              min(hullFitRatios) if hullFitRatios else 0.0,
                              len(actualBodies), ', '.join(actualBodies)))

    except:
        if ui:
            ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))

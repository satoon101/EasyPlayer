# ../addons/source-player/packages/custom/easyplayer.py

"""Provides :class:`EasyPlayer` and :class:`PlayerEffect` classes."""

# =============================================================================
# >> IMPORTS
# =============================================================================
# Python 3 Impors
#   Collections
from collections import defaultdict
#   Functools
from functools import wraps

# Source.Python Imports
#   Entities
from entities.constants import CollisionGroup
from entities.constants import MoveType
from entities.constants import TakeDamage
from entities.helpers import index_from_pointer
from entities.hooks import EntityPreHook
from entities.hooks import EntityCondition
#   Events
from events.listener import _EventListener
#   Listeners
from listeners import OnLevelShutdown
from listeners.tick import tick_delays
#   Players
from players.constants import PlayerStates
from players.entity import Player
from players.helpers import index_from_userid
from players.helpers import userid_from_index
#   Weapons
from weapons.entity import Weapon


# =============================================================================
# >> ALL DECLARATION
# =============================================================================
__all__ = (
    'EasyPlayer',
    'PlayerEffect',
)


# =============================================================================
# >> HOOKS
# =============================================================================
@EntityPreHook(EntityCondition.is_player, 'bump_weapon')
def _pre_bump_weapon(args):
    """Hooks bump_weapon function to implement weapon restrictions."""

    # Get the player and weapon entities
    player = EasyPlayer(index_from_pointer(args[0]))
    weapon = Weapon(index_from_pointer(args[1]))

    # Return False if the weapon is restricted for the player
    if weapon.classname in player.restrictions:
        return False


@EntityPreHook(EntityCondition.is_player, 'buy_internal')
def _on_buy_internal(args):
    """Hooks buy_internal function to implement buy restrictions."""

    # Get the player and weapon purchased
    player = EasyPlayer(index_from_pointer(args[0]))
    weapon = 'weapon_{}'.format(args[1])

    # Return 0 if the weapon is restricted.
    if weapon in player.restrictions:
        return 0

# Store the original fire_game_event method
_original_fire_game_event = _EventListener.fire_game_event


# Custom fire_game_event method for post listeners.
@wraps(_original_fire_game_event)
def _fire_game_event(self, game_event):

    # Call the original fire_game_event normally
    _original_fire_game_event(self, game_event)

    # Call the post functions
    event_name = game_event.get_name()
    if event_name == 'player_death':
        _post_player_death(game_event)
    elif event_name == 'player_disconnect':
        _post_player_disconnect(game_event)


# Monkey patch the fire_game_event method with the new wrapped one
_EventListener.fire_game_event = _fire_game_event


# =============================================================================
# >> GAME EVENTS
# =============================================================================
def _post_player_death(game_event):
    """Cancel any active player effects and reset player's gravity.

    :param game_event: Event provided by Source engine
    :type game_event: :class:`events.GameEvent`
    """
    player = EasyPlayer.from_userid(game_event.get_int('userid'))
    player.gravity = 1.0
    player.restrictions.clear()
    player.cancel_all_effects()


def _post_player_disconnect(game_event):
    """Clean up the players from all EasyPlayer classes.

    :param game_event: Event provided by Source engine
    :type game_event: :class:`events.GameEvent`
    """
    userid = game_event.get_int('userid')
    player = EasyPlayer.from_userid(userid)
    player.cancel_all_effects()
    _EasyPlayerMeta.discard_player(userid)


@OnLevelShutdown
def on_level_shutdown():
    """Clean up all players from all EasyPlayer classes."""
    _EasyPlayerMeta.discard_all_players()


# =============================================================================
# >> PLAYER EFFECTS
# =============================================================================
class _PlayerEffect(object):
    """Class for player effects like freeze and burn."""

    def __init__(self, descriptor_obj, player):
        """Initialize a new effect for a player.

        :param descriptor_obj: The descriptor object for the effect
        :type descriptor_obj: :class:`PlayerEffect`
        :param player: Player who to apply the effect on
        :type player: :class:`EasyPlayer`
        """
        self._descriptor_obj = descriptor_obj
        self._player = player
        self._delay = None

    def _enable(self, duration=None, *args, **kwargs):
        """Enable the effect.

        :param duration: Duration after which to cancel the effect
        :type duration: :class:`int`|:class:`NoneType`
        :param *args: Arguments to forward to the on function
        :type *args: :class:`tuple`
        :param *kwargs: Keyword arguments to forward to the on function
        :type *kwargs: :class:`dict`
        """

        # If the duration is a positive integer
        if isinstance(duration, int) and duration > 0:

            # Start a delay which will disable the effect
            self._delay = tick_delays.delay(duration, self._disable)

        # Add the effect to the player's effects
        self._player._effects[self._descriptor_obj].append(self)

        # Call the descriptor object's on-function on the player
        self._descriptor_obj._on_f(self._player, *args, **kwargs)

    def __call__(self, duration=None, *args, **kwargs):
        """Override () to call :func:`_enable`.

        :param duration: Duration after which to cancel the effect
        :type duration: :class:`int`|:class:`NoneType`
        :returns: self
        :rtype: :class:`_PlayerEffect`
        :param *args: Arguments to forward to the on function
        :type *args: :class:`tuple`
        :param *kwargs: Keyword arguments to forward to the on function
        :type *kwargs: :class:`dict`
        """
        self._enable(duration, *args, **kwargs)
        return self

    def _disable(self, *args, **kwargs):
        """Disable the effect.

        :param *args: Arguments to forward to the off function
        :type *args: :class:`tuple`
        :param *kwargs: Keyword arguments to forward to the off function
        :type *kwargs: :class:`dict`
        """

        # Remove the effect from the player's effects
        self._player._effects[self._descriptor_obj].remove(self)

        # If the player has no more effects of this type
        if not self._player._effects[self._descriptor_obj]:

            # Call the descriptor o bject's off-function on the player
            self._descriptor_obj._off_f(self._player, *args, **kwargs)

    def cancel(self, *args, **kwargs):
        """Cancel the tick_delay and disable the effect.

        :param *args: Arguments to forward to the off function
        :type *args: :class:`tuple`
        :param *kwargs: Keyword arguments to forward to the off function
        :type *kwargs: :class:`dict`
        """

        # If there is a delay object
        if self._delay is not None:

            # Cancel it
            tick_delays.cancel_delay(self._delay)
            self._delay = None

        # Disable the effect
        self._disable(*args, **kwargs)


class PlayerEffect(object):
    """Decorator similar to :class:`property()` for player effects."""

    def __init__(self, on_f=None, off_f=None):
        """Initialize a player effect with the given functions.

        :param on_f: Function to call when the effect starts
        :type on_f: :class:`function`
        :param off_f: Function to call when the effect ends
        :type off_f: :class:`function`
        """
        self._on_f = on_f
        self._off_f = off_f

    def on(self, on_f):
        """Decorator to add an :attr:`on_f` function to the effect.

        :param on_f: Function to call when the effect starts
        :type on_f: :class:`function`
        :returns: Copy of self with new :attr:`on_f`
        :rtype: :class:`PlayerEffect`
        """
        return type(self)(on_f, self._off_f)

    def off(self, off_f):
        """Decorator to add an off_f function to the effect.

        :param off_f: Function to call when the effect ends
        :type off_f: :class:`function`
        :returns: Copy of self with new :attr:`off_f`
        :rtype: :class:`PlayerEffect`
        """
        return type(self)(self._on_f, off_f)

    def __get__(self, obj, objtype=None):
        """Descriptor method to get the actual player effect.

        :param obj: The player who's accessing the effect
        :type obj: :class:`EasyPlayer`
        :param objtype: Type of the object
        :type objtype: :class:`_EasyPlayerMeta`
        :returns: The actual player effect
        :rtype: :class:`_PlayerEffect`
        """

        # Return the :class:`PlayerEffect` instance
        # when accessed through the class
        if obj is None:
            return self

        # Else return a new :class:`_PlayerEffect` instance
        return _PlayerEffect(self, obj)


# =============================================================================
# >> EASY PLAYER
# =============================================================================
class _EasyPlayerMeta(type(Player)):
    """Metaclass for :class:`EasyPlayer` and its subclasses.

    Manages all the instances of :class:`EasyPlayer`,
    making sure they get cached properly.

    Together with the event callbacks defined in :mod:`easyplayer`,
    this will also clean up players upon disonnect or map change.
    """

    # Dictionary to store all the instances of all classes,
    # in case anyone wants to subclass :class:`EasyPlayer`.
    _classes = defaultdict(dict)

    def __call__(cls, index, *args, **kwargs):
        """Instantiates the class.

        If an instance with the same userid already exists,
        return it instead of creating a new one.

        :param index: Index of the player
        :type index: :class:`int`
        :returns: Player instance from the index
        :rtype: :class:`EasyPlayer`
        """

        # Get the instance dictionary for the class
        instances = _EasyPlayerMeta._classes[cls]

        # Get the player's userid
        userid = userid_from_index(index)

        # If there is no instance with such userid
        if userid not in instances:

            # Normally create a new instance and cache it
            instances[userid] = super().__call__(index, *args, **kwargs)

        # Return the cached instance
        return instances[userid]

    @staticmethod
    def discard_player(userid):
        """Discard a player, removing him from all classes.

        :param userid: UserID of the player to discard
        :type userid: :class:`int`
        """

        # Loop through all of the instance dictionaries
        for instances in _EasyPlayerMeta._classes.values():

            # If the player exist in the dictionary
            if userid in instances:

                # Remove him from the dict
                del instances[userid]

    @staticmethod
    def discard_all_players():
        """Discard all players."""

        # Loop through all instance dictionaries and clear them
        for instances in _EasyPlayerMeta._classes.values():
            instances.clear()


class EasyPlayer(Player, metaclass=_EasyPlayerMeta):
    """Custom :class:`PlayerEntity` class with bonus player effects.

    Also implements restrictions and :method:`from_userid` classmethod.
    """

    # A dictionary which stores all the EasyPlayer's attributes
    _data = defaultdict(dict)

    def __init__(self, index):
        """Initializes an EasyPlayer instance.

        Adds :attr:`_effects` dictionary and :attr:`restrictions` set.

        :param index: Index of the player who to instantiate
        :type index: :class:`int`
        """
        super().__init__(index)
        self._effects = defaultdict(list)
        self.restrictions = set()

    def __getattr__(self, attr):
        """Get an attribute's value from the _dict if all else fails."""
        if attr in EasyPlayer._data[self.userid]:
            return EasyPlayer._data[self.userid][attr]
        return super().__getattribute__(attr)

    def __setattr__(self, attr, value):
        """Check to see if such attribute exists already."""
        try:
            super().__getattribute__(attr)
        except AttributeError:
            EasyPlayer._data[self.userid][attr] = value
        else:
            super().__setattr__(attr, value)

    @classmethod
    def from_userid(cls, userid):
        """Constructor to get an instance from an userid.

        :param userid: UserID of the player who to instantiate
        :type userid: :class:`int`
        """
        return cls(index_from_userid(userid))

    def cancel_all_effects(self):
        """Cancel all the effects from a player."""

        # Loop through all the lists of player effects
        for effect_list in self._effects.values():

            # Loop through and cancel every effect in the list
            for effect in effect_list:
                effect.cancel()

        # Clear the :attr:`_effects` dictionary
        self._effects.clear()

    def shift_property(self, prop_name, shift, duration=None):
        """Shifts player's property's value.

        :param prop_name: Name of the property to shift, e.g. 'health'
        :type prop_name: :class:`str`
        :param shift: Amount of shift to make, can be negative
        :type shift: :class:`int`
        :param duration: Revert the shift after the duration has ended
        :type duration: :class:`int`|:class:`NoneType`
        """

        # Get the current value of the property
        old_value = getattr(self, prop_name)

        # Shift the property's value by the shift amount
        setattr(self, prop_name, old_value + shift)

        # If the duration is a positive integer
        if isinstance(duration, int) and duration > 0:

            # Start a delay which will revert the shift
            tick_delays.delay(duration, self.shift_property, prop_name, -shift)

    def _update_move_type(self):
        """Update player's :attr:`move_type` to his player effects.

        This gets called whenver a movement effect starts or ends.
        Priority order: noclip > freeze > fly > walk
        """
        if self._effects[type(self).noclip]:
            self.move_type = MoveType.NOCLIP
        elif self._effects[type(self).freeze]:
            self.move_type = MoveType.NONE
        elif self._effects[type(self).fly]:
            self.move_type = MoveType.FLY
        else:
            self.move_type = MoveType.WALK

    noclip = PlayerEffect(_update_move_type, _update_move_type)
    freeze = PlayerEffect(_update_move_type, _update_move_type)
    fly = PlayerEffect(_update_move_type, _update_move_type)

    @PlayerEffect
    def paralyze(self):
        self.flags |= PlayerStates.FROZEN

    @paralyze.off
    def paralyze(self):
        self.flags &= ~PlayerStates.FROZEN

    @PlayerEffect
    def burn(self):
        self.ignite_lifetime(3600)  # 1 hour ~= infinite

    @burn.off
    def burn(self):
        self.ignite_lifetime(0)

    @PlayerEffect
    def godmode(self):
        self.set_property_uchar('m_takedamage', TakeDamage.NO)

    @godmode.off
    def godmode(self):
        self.set_property_uchar('m_takedamage', TakeDamage.YES)

    @PlayerEffect
    def noblock(self):
        self.collision_group = CollisionGroup.DEBRIS_TRIGGER

    @noblock.off
    def noblock(self):
        self.collision_group = CollisionGroup.PLAYER

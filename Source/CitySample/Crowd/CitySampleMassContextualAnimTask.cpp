// Copyright Epic Games, Inc. All Rights Reserved.

#include "CitySampleMassContextualAnimTask.h"
#include "MassSignalSubsystem.h"
#include "MassStateTreeExecutionContext.h"
#include "MassCrowdAnimationTypes.h"
#include "MassCommandBuffer.h"
#include "MassExecutionContext.h"
#include "Animation/AnimMontage.h"
#include "MassNavigationFragments.h"
#include "MassZoneGraphNavigationUtils.h"
#include "Animation/MassCrowdContextualAnimTypes.h"
#include "CrowdCharacterActor.h"
#include "MassActorSubsystem.h"
#include "StateTreeLinker.h"
#include "MassStateTreeDependency.h"

FCitySampleMassContextualAnimTask::FCitySampleMassContextualAnimTask()
{
}

bool FCitySampleMassContextualAnimTask::Link(FStateTreeLinker& Linker)
{
	Linker.LinkExternalData(MassSignalSubsystemHandle);
	Linker.LinkExternalData(MontageRequestHandle);
	Linker.LinkExternalData(TransformHandle);
	Linker.LinkExternalData(MoveTargetHandle);
	Linker.LinkExternalData(ActorHandle);

	return true;
}

void FCitySampleMassContextualAnimTask::GetDependencies(UE::MassBehavior::FStateTreeDependencyBuilder& Builder) const
{
	Builder.AddReadWrite(MassSignalSubsystemHandle);
	Builder.AddReadWrite<FMassMontageFragment>();
	Builder.AddReadOnly<FTransformFragment>();
	Builder.AddReadWrite<FMassMoveTargetFragment>();
	Builder.AddReadOnly<FMassActorFragment>();
}

EStateTreeRunStatus FCitySampleMassContextualAnimTask::EnterState(FStateTreeExecutionContext& Context, const FStateTreeTransitionResult& Transition) const
{
	const FMassStateTreeExecutionContext& MassStateTreeContext = static_cast<FMassStateTreeExecutionContext&>(Context);
	FInstanceDataType& InstanceData = Context.GetInstanceData<FInstanceDataType>(*this);

	InstanceData.Time = 0.f;

	UMassCrowdContextualAnimationDataAsset* CrowdAnimAsset = nullptr;
	const FMassActorFragment& ActorFragment = MassStateTreeContext.GetExternalData(ActorHandle);
	if (const ACitySampleCrowdCharacter* CitySampleCrowdCharacter = Cast<ACitySampleCrowdCharacter>(ActorFragment.Get()))
	{
		CrowdAnimAsset = CitySampleCrowdCharacter->CurrentContextualAnimDataAsset;
	}

	InstanceData.ComputedDuration = InstanceData.Duration;

	const FMassCrowdContextualAnimDescription* AnimDesc = CrowdAnimAsset ? CrowdAnimAsset->AnimsMap.Find(ContextualAnimName) : nullptr;
	if (AnimDesc)
	{
		const int32 NumAnims = AnimDesc->Anims.Num();
		if (NumAnims > 0)
		{
			const int32 SelectedAnimIndex = FMath::RandRange(0, NumAnims - 1);
			UE::CrowdInteractionAnim::FRequest AnimRequest;

			UContextualAnimSceneAsset* ContextualAnimAsset = AnimDesc->Anims[SelectedAnimIndex].ContextualAnimAsset;
			UAnimMontage* FallbackMontage = AnimDesc->Anims[SelectedAnimIndex].FallbackMontage;
			const FName InteractorRole = AnimDesc->InteractorRole;
			const FName AlignmentTrack = AnimDesc->AlignmentTrack;

			AnimRequest.ContextualAnimAsset = ContextualAnimAsset;
			AnimRequest.InteractorRole = InteractorRole;
			AnimRequest.AlignmentTrack = AlignmentTrack;

			FContextualAnimQueryResult& ContextualAnimQueryResult = AnimRequest.QueryResult;
			// If we have a target entity associated, use that to find the best contextual anim to play
			if (ContextualAnimAsset != nullptr && InstanceData.TargetEntity.IsSet())
			{
				if (const FTransformFragment* TargetTransformFragment = MassStateTreeContext.GetEntityManager().GetFragmentDataPtr<FTransformFragment>(InstanceData.TargetEntity))
				{
					const FTransform& TargetTransform = TargetTransformFragment->GetTransform();
					const FTransform& EntityTransform = MassStateTreeContext.GetExternalData(TransformHandle).GetTransform();

					FContextualAnimQueryParams ContextualAnimQueryParams;
					ContextualAnimQueryParams.bComplexQuery = true;
					ContextualAnimQueryParams.bFindAnimStartTime = true;
					ContextualAnimQueryParams.QueryTransform = EntityTransform;

					// If we don't find a good sync point, grab the closest one.
					if (!ContextualAnimAsset->Query(InteractorRole, ContextualAnimQueryResult, ContextualAnimQueryParams, TargetTransform))
					{
						ContextualAnimQueryParams.bComplexQuery = false;
						ContextualAnimAsset->Query(InteractorRole, ContextualAnimQueryResult, ContextualAnimQueryParams, TargetTransform);
					}
				}
			}

			// If we didn't find a proper contextual anim, or it was not set, use a simple montage instead
			if (!ContextualAnimQueryResult.Animation.IsValid())
			{
				ContextualAnimQueryResult.Animation = FallbackMontage;
			}

			if (const UAnimMontage* Montage = ContextualAnimQueryResult.Animation.Get())
			{
				// Only override movement mode if we have root motion
				if (Montage->HasRootMotion())
				{
					const UWorld* World = Context.GetWorld();
					checkf(World != nullptr, TEXT("A valid world is expected from the execution context"));

					FMassMoveTargetFragment& MoveTarget = Context.GetExternalData(MoveTargetHandle);
					MoveTarget.CreateNewAction(EMassMovementAction::Animate, *World);
					if (!UE::MassNavigation::ActivateActionAnimate(*World, Context.GetOwner(), MassStateTreeContext.GetEntity(), MoveTarget))
					{
						return EStateTreeRunStatus::Failed;
					}
				}

				// Grab the task duration from the montage.
				InstanceData.ComputedDuration = Montage->GetPlayLength();
				// Use existing fragment or push one
				FMassMontageFragment* MontageFragment = MassStateTreeContext.GetExternalDataPtr(MontageRequestHandle);
				if (MontageFragment != nullptr)
				{
					MontageFragment->Request(AnimRequest);
				}
				else
				{
					FMassMontageFragment MontageData;
					MontageData.Request(AnimRequest);
					MassStateTreeContext.GetMassEntityExecutionContext().Defer().PushCommand<FMassCommandAddFragmentInstances>(MassStateTreeContext.GetEntity(), MontageData);
				}
			}
		}
	}

	// A Duration <= 0 indicates that the task runs until a transition in the state tree stops it.
	// Otherwise we schedule a signal to end the task.
	if (InstanceData.ComputedDuration > 0.0f)
	{
		UMassSignalSubsystem& MassSignalSubsystem = MassStateTreeContext.GetExternalData(MassSignalSubsystemHandle);
		MassSignalSubsystem.DelaySignalEntity(UE::Mass::Signals::ContextualAnimTaskFinished, MassStateTreeContext.GetEntity(), InstanceData.ComputedDuration);
	}

	return EStateTreeRunStatus::Running;
}

EStateTreeRunStatus FCitySampleMassContextualAnimTask::Tick(FStateTreeExecutionContext& Context, const float DeltaTime) const
{
	FInstanceDataType& InstanceData = Context.GetInstanceData<FInstanceDataType>(*this);
	
	InstanceData.Time += DeltaTime;
	return InstanceData.ComputedDuration <= 0.0f ? EStateTreeRunStatus::Running : (InstanceData.Time < InstanceData.ComputedDuration ? EStateTreeRunStatus::Running : EStateTreeRunStatus::Succeeded);
}
